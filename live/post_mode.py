"""post_mode for a draft: original | quote | reply, decided from the draft's own source and the donor post-type mix.

docs/post_types_media.md sections 3, 5 and 8. Only a draft whose source is an X status URL can quote or reply,
and the target is always that stored URL (never searched for, never another post). Publishing stays manual: the
dashboard shows 「打开原帖」 + an 引用 / 回复 label and the reviewer quotes / replies by hand on X.

- quote: the draft was written as a `quote_comment` (the donor mix chose that shape), or a stable per-draft draw
  falls under the account's donor quote share (capped at QUOTE_CAP until we have more quote metadata).
- reply: phase 1 off. Accounts listed in FD_REPLY_ACCOUNTS (comma separated) may reply with question / one_liner
  drafts, at most one per day (the caller passes the count already given).
- Stale targets (source older than QUOTE_MAX_AGE_H at the draft day's end) stay original: quoting a days-old post
  reads oddly.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HABITS = ROOT / 'live/personas/posting_habits'
X_STATUS = re.compile(r'^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)')
QUOTE_CAP = 0.30
QUOTE_MAX_AGE_H = 72
REPLY_FORMATS = ('question', 'one_liner')


def x_target(source):
    """(canonical url, handle, post id) when the source is an X status, else None."""
    m = X_STATUS.match(str((source or {}).get('url') or '').strip())
    if not m:
        return None
    return f'https://x.com/{m.group(1)}/status/{m.group(2)}', m.group(1), m.group(2)


def quote_share(account_id, habits_dir=None):
    try:
        card = json.loads(((habits_dir or HABITS) / f'{account_id}.json').read_text())
        return min(QUOTE_CAP, float((card.get('post_type_mix') or {}).get('quote_comment') or 0))
    except (OSError, ValueError):
        return 0.0


def _draw(key):
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 16 ** 8


def reply_accounts(env=None):
    return {a.strip() for a in (env if env is not None else os.environ).get('FD_REPLY_ACCOUNTS', '').split(',')
            if a.strip()}


def _fresh(source, day):
    try:
        pub = datetime.fromisoformat(str(source.get('published_at')).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return False
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    # end of the inbox day (a Beijing calendar date since Oct 7) = when its last slot (22:59 北京时间) is gone
    end = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo('Asia/Shanghai')) + timedelta(days=1) if day else datetime.now(timezone.utc)
    return end - pub <= timedelta(hours=QUOTE_MAX_AGE_H)


def decide(row, habits_dir=None, replies_given=0, env=None, own_handles=()):
    """{'post_mode', 'quote_target_url' | 'reply_to_url', 'post_mode_why'} for one inbox row."""
    src = row.get('source') or {}
    target = x_target(src)
    if not target:
        return {'post_mode': 'original', 'post_mode_why': 'source is not an X post'}
    url, handle, _pid = target
    if handle.lower() in {h.lower().lstrip('@') for h in own_handles if h}:
        return {'post_mode': 'original', 'post_mode_why': 'source is one of our own accounts'}
    if not _fresh(src, row.get('day')):
        return {'post_mode': 'original', 'post_mode_why': f'X source older than {QUOTE_MAX_AGE_H}h'}
    fmt = (row.get('post_format') or {}).get('type')
    acct = row.get('account_id') or ''
    if acct in reply_accounts(env) and fmt in REPLY_FORMATS and replies_given < 1:
        return {'post_mode': 'reply', 'reply_to_url': url, 'post_mode_why': f'reply opt-in account, {fmt} draft'}
    if fmt == 'quote_comment':
        return {'post_mode': 'quote', 'quote_target_url': url, 'post_mode_why': 'written as quote_comment'}
    share = quote_share(acct, habits_dir)
    draw = _draw(f"{row.get('id')}|quote")
    if draw < share:
        return {'post_mode': 'quote', 'quote_target_url': url,
                'post_mode_why': f'donor quote share {share:.2f} (draw {draw:.2f})'}
    return {'post_mode': 'original', 'post_mode_why': f'donor quote share {share:.2f} (draw {draw:.2f})'}
