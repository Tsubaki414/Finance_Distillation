"""Thin-lane sources (Oct 13): extra free, no-key analysis feeds for the accounts whose pools are SUPPLY-bound
(measured in /workspace/x/thin_lanes/measure_pool.py; report /workspace/x/cc_jobs/thin_lanes_REPORT.md).

The rows live in live/thin_lane_sources.json, not in source_registry.json / source_licence.json, so those two files
stay byte-identical to the pre-Oct-13 set. FD_THIN_LANE_SRC (default 1) merges them into the readers the daily path
uses:
  - ingest: scripts/run_content_adapters.newsletter_feeds (daily_ingest fetchers)
  - routing / tags / compose scope: live/source_routes (route_accounts + route_beats, deterministic tags, no Jev)
  - licence tier + aliases: live/registry.source_licence_tier, live/attribution_frame.aliases
  - publisher name: live/attribution_frame.publisher_name
FD_THIN_LANE_SRC=0 restores exactly the old source set: no fetch, no route, no licence entry, and units these sources
already put in the store are offered to no account (source_routes.allowed) and have no writable licence tier.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parent / 'thin_lane_sources.json'
SWITCH = 'FD_THIN_LANE_SRC'


def enabled(env=None):
    return (env if env is not None else os.environ).get(SWITCH, '1') != '0'


@lru_cache(maxsize=4)
def _load(path=str(PATH)):
    return json.loads(Path(path).read_text())


def ids(path=None):
    """Ids of every thin-lane source (whether or not the switch is on)."""
    return frozenset(r['id'] for r in _load(str(path or PATH)).get('sources') or [])


def rows(env=None, path=None):
    """Registry rows to merge (empty when the switch is off)."""
    if not enabled(env):
        return []
    return [dict(r) for r in _load(str(path or PATH)).get('sources') or []]


def licence(env=None, path=None):
    """{source_id: licence entry} to merge into source_licence.json tiers (empty when the switch is off)."""
    if not enabled(env):
        return {}
    return {k: dict(v) for k, v in (_load(str(path or PATH)).get('licence') or {}).items()}


def merged_registry_rows(base_rows, env=None):
    """base_rows (source_registry.json 'sources') plus the thin-lane rows; a base id is never overridden."""
    have = {r.get('id') for r in base_rows}
    return list(base_rows) + [r for r in rows(env) if r['id'] not in have]


def merged_licence(base, env=None):
    """base (source_licence.json 'tiers') plus the thin-lane entries; a base entry is never overridden."""
    extra = licence(env)
    if not extra:
        return base
    return {**{k: v for k, v in extra.items() if k not in base}, **base}


def blocked(source_id, env=None):
    """True for a thin-lane source while the switch is off (its stored units are offered to no account)."""
    return not enabled(env) and source_id in ids()
