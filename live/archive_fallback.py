"""Oct 12 (Fiona, option 2; FD_ARCHIVE_FALLBACK_ONLY, default 1): 回看 / 常青 only on days with no fresh standalone.

Measured (/workspace/x/offlane/measure_archive_slot.py): an archive / evergreen row (arc-* / evg-*, post_kind
archive_lookback) took the account's single standalone slot while the account still had a fresh on-lane standalone
candidate - 9 of 12 such accounts on 10-11, 5 of 25 on 10-12. Two deterministic rules, no model call:

1. archive hook (scripts/daily_compose.py -> archive_lookback.fill_gaps): an account whose post-gate standalone pool
   (pool after the tried / lane / fresh gates, i.e. what select() considers) is still non-empty after the run's last
   round it took part in gets no archive draft; skipped accounts + reason go into the summary.
2. --fill rounds / midday composes: an account whose ready standalone rows are ALL archive rows still pending review
   and unpublished has its standalone slot opened to select(); once a fresh standalone lands ready, those archive rows
   are superseded (compose_inbox.supersede, reason 'archive_fallback'). Reviewed / published archive rows never yield.
FD_ARCHIVE_FALLBACK_ONLY=0 restores the old behaviour exactly.
"""
from __future__ import annotations

import os

REASON = 'archive_fallback'
POST_KIND = 'archive_lookback'


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_ARCHIVE_FALLBACK_ONLY', '1') != '0'


def is_archive(row):
    return row.get('post_kind') == POST_KIND or str(row.get('id') or '').startswith(('arc-', 'evg-'))


def is_standalone(row):
    """Same split as daily_compose.row_slot_kind: not a reply / quote and not the diary slot."""
    e = row.get('engagement') or {}
    if (row.get('post_format') or {}).get('engage') in ('reply', 'quote') or e.get('mode') in ('reply', 'quote'):
        return False
    return row.get('slot') != 'diary'


def _ready(row):
    return (not row.get('superseded') and not row.get('held') and row.get('draft_status') == 'draft_ready'
            and bool((row.get('text') or '').strip()))


def can_yield(row, published=None):
    """An archive row that may give its slot up: still pending review and not published."""
    return (is_archive(row) and _ready(row) and row.get('review_status', 'pending') == 'pending'
            and not row.get('published') and not (published and published(row)))


def displaceable(rows, published=None):
    """{account: [archive row ids]} for accounts whose ready standalone rows are all yieldable archive rows."""
    by_acct = {}
    for r in rows or ():
        if r.get('account_id') and _ready(r) and is_standalone(r):
            by_acct.setdefault(r['account_id'], []).append(r)
    return {a: [r['id'] for r in rs] for a, rs in by_acct.items()
            if all(can_yield(r, published) for r in rs)}


def skip_accounts(last):
    """{account: reason} from daily_compose's per-account last-round state (key 'standalone_left': post-gate standalone
    pool of that round minus its standalone picks). Accounts without that key are not skipped."""
    out = {}
    for a, v in (last or {}).items():
        n = (v or {}).get('standalone_left')
        if n:
            out[a] = (f"{REASON}: {n} fresh standalone candidate(s) left in the post-gate pool "
                      f"(round {(v or {}).get('round')})")
    return out


def supersede_for(row, arc_ids, published=None, base=None):
    """A fresh ready standalone `row` landed: supersede that account's yieldable archive rows. Returns ids done."""
    from live import compose_inbox
    if is_archive(row) or not _ready(row) or not is_standalone(row):
        return []
    done = []
    for aid in arc_ids or ():
        try:
            old = compose_inbox.get(aid, base=base)
        except (OSError, ValueError):
            continue
        if old.get('account_id') != row.get('account_id') or not can_yield(old, published):
            continue
        if compose_inbox.supersede(aid, by=row['id'], reason=REASON, base=base):
            done.append(aid)
    return done
