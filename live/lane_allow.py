"""Per-account topic allowlist + persona-consistent off-lane quota (Oct 11 account audit fix 2).

live/personas/posting_habits/account_mix.json (local only, not in git; scripts/build_account_mix.py from the audit's
aggregate donor statistics) gives each account
  allow      - the lane's own buckets + donor top buckets (>= 6% of donor topic posts) inside the lane family,
  offlane_ok - other donor buckets (>= 2.5%): a deliberate, persona-consistent aside, at most offlane_per_week (1-3)
               a week (counted over the last 7 Beijing days of ready drafts tagged offlane_aside),
everything else is off-lane: the pick is not written by this account but handed to a fitting account with a free slot
(lane_fit.reassign_target first - the BTC/ETH macro / niche reassignment of 6b45ef5 - then any same-language account
whose core lane buckets have it). Unknown bucket (no label, no keyword) = no gate. FD_LANE_ALLOW=0 turns it off.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'live' / 'personas' / 'posting_habits' / 'account_mix.json'   # local only (donor-derived), like the habit cards
NEUTRAL = {'personal_life', 'culture_sports_other'}
_MIX = {}


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_LANE_ALLOW', '1') != '0'


def mix(path=None):
    p = str(path or os.environ.get('FD_ACCOUNT_MIX') or PATH)
    if p not in _MIX:
        try:
            _MIX[p] = json.loads(Path(p).read_text()).get('accounts') or {}
        except (OSError, ValueError):
            _MIX[p] = {}
    return _MIX[p]


def cfg(account):
    return mix().get(account) or {}


def verdict(account, bucket):
    """'on' | 'offlane_ok' | 'off' | None (no gate: unknown bucket / account / switch off)."""
    c = cfg(account)
    if not enabled() or not c or not bucket or bucket in NEUTRAL:
        return None
    if bucket in (c.get('allow') or ()):
        return 'on'
    if bucket in (c.get('offlane_ok') or ()):
        return 'offlane_ok'
    return 'off'


def quota(account):
    return int(cfg(account).get('offlane_per_week') or 1)


def offlane_used(account, rows):
    return sum(1 for r in rows if r.get('account_id') == account and r.get('offlane_aside'))


def fit_accounts(bucket, lang, exclude=(), accounts=None):
    """Same-language accounts whose core lane buckets hold the bucket (handover targets)."""
    out = []
    for aid, c in mix().items():
        if aid in exclude or str(c.get('lang') or '')[:2] != str(lang or '')[:2]:
            continue
        if accounts is not None and aid not in accounts:
            continue
        core = c.get('core') or []   # a handover goes to an account whose OWN lane is this topic, not a donor side topic
        if bucket in core:
            out.append((core.index(bucket), aid))
    return [a for _i, a in sorted(out)]
