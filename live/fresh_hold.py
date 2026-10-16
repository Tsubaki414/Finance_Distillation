"""Freshness HARD gate (Oct 12 2026): the last check before a draft is written to the review inbox.

The 10-11/10-12 audit found 75% of shipped originals were based on sources older than 48 h at their scheduled
slot: `daily_compose.fresh_gate` drops stale items from the selection pool, but three paths still reached the
inbox — (a) sources with no parseable `published_at` were kept as `undated_kept` and never date-checked again,
(b) the FD_FRESH_LOOKBACK fallback re-inserts items aged up to 120 h for starved accounts, and (c) the
回看 / 常青 fill path (live/archive_lookback.py) writes its rows through a different code path that never ran
the gate at all. A pool-time gate cannot fix these: the pool is rebuilt per round and the fallback is allowed
to re-introduce what the gate removed.

This module enforces the rule at the only place that cannot be bypassed — immediately before
`compose_inbox.add(...)` — using the SOURCE PUBLISH time against the draft's own scheduled slot:

  * news / original drafts (everything that is not an archive post): HOLD when the source is older than
    FD_FRESH_MAX_H (48) h at the slot, or when the publish time is missing / unparseable ("unknown publish
    time is not fresh").
  * archive posts (archive_lookback / archive_evergreen, ids arc-* / evg-*, label 回看): exempt from the 48 h
    rule — they are curated archive material by design — but only while they stay framed; an archive body
    that names an event older than FD_STALE_MAX_DAYS without a look-back frame (and, for then-vs-now, a today
    tie) is held, reusing live/stale_frame.findings(archive=True).

Kill switch: FD_FRESH_HOLD=0 disables the whole gate (default 1 = on). FD_FRESH_MAX_H / FD_FRESH_SLOT_LEAD_H
shared with the pool-time gate so one knob tunes both. Never publishes anything.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

HOLD_CODE = 'stale_source'
CODE_UNFRAMED = 'archive_unframed'

ARCHIVE_ID = re.compile(r'^(?:arc|evg)-', re.I)
ARCHIVE_KIND = re.compile(r'^archive', re.I)
EXPLICIT_FRAME = re.compile(r'\s*(回看|回顾|Look(ing)? back|Lookback|Throwback)', re.I)


def explicit_frame_required(env: dict | None = None) -> bool:
    """FD_FRESH_ARCHIVE_EXPLICIT=0 restores 'any archive row without dated language passes'."""
    return (env or os.environ).get('FD_FRESH_ARCHIVE_EXPLICIT', '1') != '0'


def enabled(env: dict | None = None) -> bool:
    return (env or os.environ).get('FD_FRESH_HOLD', '1') != '0'


def max_age_h(env: dict | None = None) -> float:
    try:
        return float((env or os.environ).get('FD_FRESH_MAX_H', '48'))
    except ValueError:
        return 48.0


def _ts(value):
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def is_archive_row(row: dict) -> bool:
    """True for 回看 / 常青 rows (archive fill path), which follow the archive framing rule instead of 48 h."""
    rid = str(row.get('id') or '')
    kind = str(row.get('post_kind') or row.get('post_type') or '')
    return bool(ARCHIVE_ID.match(rid) or ARCHIVE_KIND.match(kind) or row.get('label') == '回看'
                or str(row.get('draft_origin') or '') == 'archive')


def evergreen_exempt(env: dict | None = None) -> bool:
    return (env if env is not None else os.environ).get('FD_FRESH_EVERGREEN_EXEMPT', '1') != '0'


def is_evergreen_row(row: dict) -> bool:
    """常青 rows: archive.variant 'evergreen' (arc-* ids from the archive fill path) or evg-* ids."""
    return (str((row.get('archive') or {}).get('variant') or '') == 'evergreen'
            or str(row.get('id') or '').startswith('evg-'))


def source_age_h(row: dict) -> float | None:
    """Age of the row's source at the draft's scheduled slot, in hours (None when either side is unparseable)."""
    src = row.get('source') or {}
    pub = _ts(src.get('published_at'))
    if pub is None:
        return None
    slot = _ts(row.get('suggested_post_time_london')) or datetime.now(timezone.utc)
    return (slot - pub).total_seconds() / 3600.0


def check(row: dict, env: dict | None = None) -> tuple[bool, str | None, dict]:
    """(hold, hold_reason, detail) for one inbox row about to be written.

    Empty text rows are left to the existing empty-text logic (nothing to gate)."""
    if not enabled(env):
        return False, None, {'skipped': 'FD_FRESH_HOLD=0'}
    if not str(row.get('text') or row.get('body') or '').strip():
        return False, None, {'skipped': 'no text'}

    if str(row.get('post_kind') or row.get('post_type') or '') == 'mindmap' or str(row.get('id') or '').startswith('mm-'):
        # Oct 16 (Fiona): mind-map fill rows summarise long-form blogs / transcripts / books: freshness-exempt like 常青
        # (the source is dated in row['source'] and credited in the image footer).
        return False, None, {'mindmap': True, 'exempt': 'freshness'}

    if is_archive_row(row):
        # Archive material is deliberately old: gate it on framing, not on age.
        try:
            from live import stale_frame
            body = str(row.get('body') or row.get('text') or '')
            day = row.get('day')
            f = stale_frame.findings(body, (row.get('lang') or 'zh')[:2], day, archive=True)
        except Exception as exc:   # noqa: BLE001 - a broken checker never holds a draft on its own
            return False, None, {'error': f'{type(exc).__name__}: {exc}'[:160]}
        if f:
            detail = dict(f[0])
            return True, f'{CODE_UNFRAMED}: ' + str(detail.get('detail') or '')[:160], detail
        # Fiona 12 Oct: archive material is exempt from the 48 h rule ONLY when explicitly framed as 回看
        # (body opens with 回看 / Look back). Unframed 常青/evergreen rows fall through to the age check.
        if EXPLICIT_FRAME.match(body) or not explicit_frame_required(env):
            return False, None, {'archive': True, 'framed': True}
        # Oct 13 07:56 (Fiona): 常青 / evergreen rows are timeless by design - exempt from the 48 h hold (they only run
        # as a fallback when the account has no fresh candidate: FD_ARCHIVE_FALLBACK_ONLY). FD_FRESH_EVERGREEN_EXEMPT=0
        # restores the age check for them.
        if is_evergreen_row(row) and evergreen_exempt(env):
            return False, None, {'archive': True, 'evergreen': True}

    age = source_age_h(row)
    pub = (row.get('source') or {}).get('published_at')
    limit = max_age_h(env)
    if age is None:
        detail = {'reason': 'unknown publish time', 'published_at': pub, 'max_h': limit, 'age_h': None}
        return True, f'{HOLD_CODE}: unknown source publish time (news drafts need a dated source)', detail
    if age > limit:
        detail = {'reason': 'source older than the freshness limit', 'published_at': pub, 'max_h': limit,
                  'age_h': round(age, 1)}
        return True, f'{HOLD_CODE}: source {detail["age_h"]}h old at the slot (> {limit:g}h)', detail
    return False, None, {'published_at': pub, 'age_h': round(age, 1)}


def apply(row: dict, env: dict | None = None, log=None) -> dict:
    """Enforce the gate on one row in place. Never un-holds a row that was held for another reason."""
    if row.get('held') and row.get('hold_reason'):
        return row
    hold, reason, detail = check(row, env)
    row['fresh_hold'] = detail
    if hold:
        row['held'] = True
        row['hold_reason'] = reason
        if row.get('draft_status') == 'draft_ready':
            row['draft_status'] = 'needs_review'
        if log:
            log(f"[fresh_hold] {row.get('account_id')} {row.get('id')}: {reason}")
    return row
