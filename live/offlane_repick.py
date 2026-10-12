"""Oct 12 (FD_OFFLANE_REPICK, default 1): no re-pick of a source an account already got HELD off_lane today.

10-12 --fill: crypto_btc_cycle_zh was handed the same ChainCatcher Polymarket packet by the 'handover' round in every
round (it came from crypto_prediction_zh's pool, so tried_sources - which filters the account's own pool - never saw
it) and every draft was held off_lane by the final lane check: 4 wasted drafts in one fill, 8 for the day.

Rules, read from the drafting day's inbox rows (deterministic, no model call):
- an (account, source) pair that already has an off_lane HOLD today is not picked again by any select round;
- an account with >= BLOCK_AT off_lane holds today gets no further off-lane-risk picks that day: no 'handover' /
  'relax' picks, and no packet the pre-pick lane checks (lane_fit.macro_check / packet_check) already reject. It falls
  through to its next on-lane candidate or nothing.
FD_OFFLANE_REPICK=0 restores the old planner exactly.
"""
from __future__ import annotations

import os

CODE = 'off_lane'
BLOCK_AT = 2
RISK_ROUNDS = ('handover', 'relax')


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_OFFLANE_REPICK', '1') != '0'


def is_offlane_hold(row):
    return bool(row.get('held')) and str(row.get('hold_reason') or '').startswith(CODE)


def source_keys(src):
    src = src or {}
    return {src.get('id'), src.get('source_id'), src.get('title'), src.get('source_hash')} - {None, ''}


def day_state(rows):
    """{account: {'keys': source keys held off_lane today, 'holds': distinct off_lane-held row ids}}."""
    out = {}
    for r in rows or ():
        if not is_offlane_hold(r) or not r.get('account_id'):
            continue
        st = out.setdefault(r['account_id'], {'keys': set(), 'holds': set()})
        st['keys'] |= source_keys(r.get('source'))
        st['holds'].add(str(r.get('id')))
    return out


def held_before(state, account, src):
    """True when this account already got this source HELD off_lane today."""
    st = (state or {}).get(account)
    return bool(st and source_keys(src) & st['keys'])


def blocked(state, account):
    """True when the account has >= BLOCK_AT off_lane holds today (no more off-lane-risk picks)."""
    st = (state or {}).get(account)
    return bool(st and len(st['holds']) >= BLOCK_AT)


def risky(account_cfg, text, own_x=False):
    """Deterministic pre-pick lane risk: the same checks lane_gate runs on an account's own pool."""
    from live import lane_fit
    if not lane_fit.macro_check(account_cfg, text)['ok']:
        return True
    return not lane_fit.packet_check(account_cfg, text, own_x=own_x)['ok']
