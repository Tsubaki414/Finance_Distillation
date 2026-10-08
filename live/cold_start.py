"""Cold-start format bias and media priority (Oct 8 evening, views diagnosis: 22 FD posts, median 4 / 113 views,
0 images, 0 replies; donors that post images get 19-71% follower reach).

- cold start (FD_COLD_START, default 1): an account in its first `window_days` (live/cold_start.json; null first day =
  not posting yet = cold) prefers fresh hot X posts it can quote (own / breadth X sources, <= 24h, not our own
  handles; when the post carries x_metrics it also needs likes >= 20 or views >= 3000) and writes those as
  quote_comment drafts with probability COLD_QUOTE_SHARE (deterministic per draft), and post_mode's donor quote share
  gets the same floor for such drafts.
- media priority (FD_MEDIA_PRIORITY, default 1): an account whose donors post images often (media_profiles
  image_rate >= IMAGE_HEAVY) ranks packets that can carry a real chart / screenshot (a ticker or data series the
  chart fetchers know, or >= 2 numbers) ahead of otherwise equal ones, and its p_image is raised toward the donors'
  image rate (live/media_real.decide).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'live' / 'cold_start.json'
COLD_QUOTE_SHARE = 0.6
HOT_MAX_AGE_H = 24
HOT_MIN_LIKES = 20
HOT_MIN_VIEWS = 3000
IMAGE_HEAVY = 0.4          # donor image_rate at or above this = "the persona's donors use images"
MEDIA_BOOST = 1.6          # p_image x this for image-heavy accounts, capped at the donors' image rate
_CFG = None


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_COLD_START', '1') != '0'


def media_enabled(env=None):
    return (env if env is not None else os.environ).get('FD_MEDIA_PRIORITY', '1') != '0'


def config():
    global _CFG
    if _CFG is None:
        try:
            _CFG = json.loads(CONFIG.read_text())
        except (OSError, ValueError):
            _CFG = {'window_days': 14, 'default_first_day': None, 'first_day': {}}
    return _CFG


def first_day(account_id, cfg=None):
    cfg = cfg or config()
    table = cfg.get('first_day') or {}
    raw = table[account_id] if account_id in table else cfg.get('default_first_day')
    return date.fromisoformat(raw) if raw else None


def is_cold(account_id, day, cfg=None):
    """True while the account is inside its first window_days of posting (or has not started)."""
    if not enabled():
        return False
    cfg = cfg or config()
    day = date.fromisoformat(day) if isinstance(day, str) else day
    start = first_day(account_id, cfg)
    return start is None or day < start + timedelta(days=int(cfg.get('window_days') or 14))


def _ts(value):
    try:
        t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def hot_quote_target(source, ref, own_handles=()):
    """True for a fresh hot X status this account could quote."""
    from live.post_mode import x_target
    target = x_target(source)
    if not target:
        return False
    if target[1].lower() in {str(h).lower().lstrip('@') for h in own_handles if h}:
        return False
    t = _ts((source or {}).get('published_at'))
    if t is None or ref - t > timedelta(hours=HOT_MAX_AGE_H) or t - ref > timedelta(hours=1):
        return False
    m = (source or {}).get('x_metrics') or {}
    if m:
        return (m.get('likes') or 0) >= HOT_MIN_LIKES or (m.get('views') or 0) >= HOT_MIN_VIEWS
    return True


def draw(key):
    return int(hashlib.sha256(f'cold-start|{key}'.encode()).hexdigest()[:8], 16) / 16 ** 8


def force_quote(account_id, day, source, ref, key, own_handles=()):
    """quote_comment for this pick? (cold account, hot fresh X target, deterministic draw < COLD_QUOTE_SHARE)."""
    return (is_cold(account_id, day) and hot_quote_target(source, ref, own_handles)
            and draw(f'{account_id}|{key}') < COLD_QUOTE_SHARE)


_PROFILES = None


def image_rate(account_id):
    global _PROFILES
    if _PROFILES is None:
        try:
            _PROFILES = json.loads((ROOT / 'live' / 'media_profiles.json').read_text()).get('accounts') or {}
        except (OSError, ValueError):
            _PROFILES = {}
    return float((_PROFILES.get(account_id) or {}).get('image_rate') or 0.0)


def image_heavy(account_id):
    return media_enabled() and image_rate(account_id) >= IMAGE_HEAVY


def boosted_p_image(account_id, p_image):
    """p_image raised toward the donors' image rate for image-heavy accounts (unchanged otherwise)."""
    if not image_heavy(account_id):
        return p_image
    return round(min(max(p_image, p_image * MEDIA_BOOST), image_rate(account_id)), 4)


def chartable(text, n_numbers=0):
    """A real chart / screenshot can go with this packet: a ticker / data series the fetchers know, or >= 2 numbers."""
    from live import charts
    try:
        if charts.pick_subject(text) or charts.pick_series(text):
            return True
    except Exception:   # noqa: BLE001
        pass
    return n_numbers >= 2
