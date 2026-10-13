"""Account-scoped research sources (Oct 7, fd20).

A live/source_registry.json row with `route_accounts` (and `route_beats`) is scoped like the fd20 X sources:
  - ingest: its units skip Jev routing / targeting and get the route beats as deterministic tags
    (beat_rules tag shape, confidence 0.75), so they land in units_for_persona(<beat>);
  - compose: scripts/daily_compose.candidates() only offers them to the listed accounts.
Rows without `route_accounts` are unaffected.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent / 'source_registry.json'
CONFIDENCE = 0.75
RULE = 'source-routes-v1'


@lru_cache(maxsize=8)
def _routes(path=str(REGISTRY), thin=False):
    from live import thin_lane_src
    out = {}
    rows = json.loads(Path(path).read_text()).get('sources') or []
    if thin:   # Oct 13 (FD_THIN_LANE_SRC): thin-lane sources from live/thin_lane_sources.json
        rows = thin_lane_src.merged_registry_rows(rows)
    for row in rows:
        if row.get('route_accounts') and row.get('enabled', True):
            out[row['id']] = {'accounts': tuple(row['route_accounts']), 'beats': tuple(row.get('route_beats') or ())}
    return out


def route(source_id, path=None):
    from live import thin_lane_src
    return _routes(str(path or REGISTRY), path is None and thin_lane_src.enabled()).get(source_id)


def allowed(source, account, path=None):
    """False only for a routed source offered to an account outside its route, or a thin-lane source while
    FD_THIN_LANE_SRC=0 (its already stored units go to no account)."""
    from live import thin_lane_src
    sid = (source or {}).get('source_id')
    if path is None and thin_lane_src.blocked(sid):
        return False
    r = route(sid, path)
    return r is None or account in r['accounts']


def tags_for(units, source_id, existing=None, path=None):
    """{unit_id: tags} adding the route beats (existing tags are kept)."""
    r = route(source_id, path)
    if not r or not r['beats']:
        return {}
    existing = existing or {}
    tag = {'verdict': 'relevant', 'confidence': CONFIDENCE, 'rule': f'{RULE}:{source_id}'}
    return {u['unit_id']: {**(existing.get(u['unit_id']) or {}), **{b: dict(tag) for b in r['beats']}} for u in units}
