"""Human review inbox for composed (judgment) drafts of the 20 main accounts (Oct 7, fd20).

One JSON file per draft under <root>/<day>/<draft_id>.json (root: FD_COMPOSE_INBOX or live/store/compose_inbox,
ignored by git). Every draft enters as review_status='pending', publishable=False. A human decision is one of
approve / minor_edit / major_edit / reject, with reviewer and reason; the reviewed text is hashed and the
decision must name the text version it was made on (stale versions are refused). Nothing here publishes:
publishing_enabled is always False and there is no publish call.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from hashlib import sha256
from pathlib import Path

from live import lanes   # Oct 16: atomic writes + short per-day lock (FD_LANES=0: plain writes, no lock)

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ('approve', 'minor_edit', 'major_edit', 'reject')
_ID = re.compile(r'^[A-Za-z0-9_.-]+$')


def root():
    return Path(os.environ.get('FD_COMPOSE_INBOX') or ROOT / 'live' / 'store' / 'compose_inbox')


def text_hash(text):
    return sha256((text or '').encode('utf-8')).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _path(draft_id, day=None, base=None):
    if not _ID.match(draft_id or ''):
        raise ValueError('bad draft id')
    base = Path(base or root())
    if day:
        return base / day / f'{draft_id}.json'
    hits = sorted(base.glob(f'*/{draft_id}.json'))
    if not hits:
        raise KeyError(draft_id)
    return hits[-1]


def hold_status_sync_enabled(env=None):
    return (env if env is not None else os.environ).get('FD_HOLD_STATUS_SYNC', '1') != '0'


def sync_hold_status(row, env=None):
    """Oct 12 (FD_HOLD_STATUS_SYNC, default 1): a HELD new row is never left draft_status='draft_ready'.

    10-12: 29 inbox rows were held=True but draft_ready, because the compose-path holds (off_lane lane fit,
    arbitration losers, stale_frame in daily_compose.inbox_row; off-path rescans) set only held / hold_reason. Every
    row written through add() passes here: held, not superseded, draft_status draft_ready / empty -> needs_review,
    publishable False, hold_reason kept. Never changes which rows are held; other statuses (blocked, not_suitable,
    expired ...) and superseded rows are left alone. In place; returns the row. FD_HOLD_STATUS_SYNC=0: no-op."""
    if not hold_status_sync_enabled(env) or not row.get('held') or row.get('superseded'):
        return row
    if row.get('draft_status') in ('draft_ready', None, ''):
        row['hold_status_from'] = row.get('draft_status')
        row['draft_status'] = 'needs_review'
    row['publishable'] = False
    return row


def _write(path, row):
    text = json.dumps(row, ensure_ascii=False, indent=2, default=str) + '\n'
    if lanes.enabled():
        lanes.atomic_write_text(path, text)
    else:
        path.write_text(text)


def _rmw_lock(path):
    """Per-file read-modify-write lock (supersede / review of one draft file; add of the same id). Separate lock file
    name from the day inbox lock daily_compose holds, so the two never nest on one file."""
    import contextlib
    if not lanes.enabled():
        return contextlib.nullcontext()
    import zlib
    return lanes.day_lock(path.parent.name, 'row%02d' % (zlib.crc32(path.stem.encode()) % 64))   # 64 buckets, not a file per row


def add(row, base=None):
    """Store one draft row (needs id, day, account_id, text). Returns the stored row."""
    for key in ('id', 'day', 'account_id', 'text'):
        if not row.get(key) and key != 'text':
            raise ValueError(f'inbox row needs {key}')
    sync_hold_status(row)
    from live import own_voice_strip
    own_voice_strip.clean_row(row)   # Oct 13: no attribution line / @handle in any draft type
    stored = {**row, 'text_hash': text_hash(row.get('text')), 'review_status': row.get('review_status', 'pending'),
              'publishable': False, 'publishing_enabled': False, 'reviews': list(row.get('reviews') or []),
              'stored_at': row.get('stored_at') or _now()}
    path = _path(stored['id'], stored['day'], base)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _rmw_lock(path):
        _write(path, stored)
    return stored


def get(draft_id, base=None):
    return json.loads(_path(draft_id, base=base).read_text())


def days(base=None):
    base = Path(base or root())
    return sorted((p.name for p in base.iterdir() if p.is_dir()), reverse=True) if base.exists() else []


def rows(day=None, account=None, base=None):
    base = Path(base or root())
    day = day or next(iter(days(base)), None)
    if not day or not (base / day).is_dir():
        return []
    out = []
    for p in sorted((base / day).glob('*.json')):
        try:
            r = json.loads(p.read_text())
        except ValueError:
            continue
        if account and r.get('account_id') != account:
            continue
        out.append(r)
    return sorted(out, key=lambda r: (r.get('no') or 99, r.get('suggested_post_time_london') or ''))


def supersede(draft_id, *, by, reason, base=None):
    """Soft-replace a draft by a newer one (rerun / rewrite of the same source): the old file stays, marked superseded
    and held, with superseded_by pointing at the new draft. Never deletes; human-reviewed drafts are left alone."""
    path = _path(draft_id, base=base)
    with _rmw_lock(path):
        row = json.loads(path.read_text())   # re-read inside the lock: a review that landed meanwhile is kept
        if row.get('superseded') or row.get('review_status', 'pending') != 'pending':
            return None
        row.update(superseded=True, held=True, superseded_by=by, superseded_reason=reason, superseded_at=_now())
        _write(path, row)
    return row


def review(draft_id, *, decision, reviewer, reason, text, expected_hash, base=None):
    """Record one human decision. Edits need minor_edit/major_edit; approve/reject keep the text unchanged."""
    if decision not in DECISIONS:
        raise ValueError(f'decision must be one of {DECISIONS}')
    if not (reviewer or '').strip() or not (reason or '').strip():
        raise ValueError('reviewer and reason are required')
    path = _path(draft_id, base=base)
    with _rmw_lock(path):
        return _review_locked(path, draft_id, decision, reviewer, reason, text, expected_hash)


def _review_locked(path, draft_id, decision, reviewer, reason, text, expected_hash):
    row = json.loads(path.read_text())
    current = row.get('reviewed_text', row.get('text') or '')
    if expected_hash != text_hash(current):
        raise ValueError('stale version: the draft changed since you opened it; reload')
    changed = text != current
    if decision in ('approve', 'reject') and changed:
        raise ValueError(f'{decision} cannot change the text; use minor_edit or major_edit')
    if decision in ('minor_edit', 'major_edit') and not changed:
        raise ValueError('an edit decision needs an actual edit')
    entry = {'id': 'rev-' + uuid.uuid4().hex[:12], 'recorded_at': _now(), 'decision': decision,
             'reviewer': reviewer.strip(), 'reason': reason.strip(), 'label_source': 'human',
             'before_hash': expected_hash, 'after_hash': text_hash(text),
             'edit_distance': round(1 - SequenceMatcher(a=current, b=text, autojunk=False).ratio(), 4)}
    row['reviews'] = list(row.get('reviews') or []) + [entry]
    row['review_status'] = {'approve': 'approved', 'reject': 'rejected'}.get(decision, 'edited')
    if changed:
        row['reviewed_text'] = text
    row['publishable'] = False   # approval is a label; publishing stays manual and outside this system
    _write(path, row)
    return entry
