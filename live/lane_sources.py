"""Lane material for the niche accounts in the daily ingest (Oct 8 evening, PM_PLAN item 4 / pm_sources).

Two parts, both off with FD_ACCOUNTS_NEW=0 (no niche accounts) and each with its own switch:
  1. structured sources (live/adapters/lane_data.py + polymarket / defillama_yields): no model call, $0; registered in
     daily_ingest.default_fetchers as 'lanes:<source_id>' and routed by source_registry route_accounts.
     FD_LANE_DATA_SOURCES=0 keeps only the two Oct 8 sources.
  2. lane flashes (live/adapters/lane_flashes.py): crypto flash desks filtered to lane words, extracted with the cheap
     batched flash EXTRACT inside their OWN ring fence (FD_LANE_FLASH_BUDGET_USD, default $0.25 per run, inside the
     ingest --cost-cap-usd and separate from the 7x24 flash fence), at most FD_LANE_FLASH_MAX (40) per run and
     FD_LANE_FLASH_PER_LANE (8) per lane. Units get the route beats as deterministic tags (no Jev call).
     FD_LANE_FLASHES=0 turns it off.
Measured 10-08: flash EXTRACT ~ $0.0018 per flash -> 40 flashes ~ $0.07 per run (two pulls a day ~ $0.15).
"""
from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta, timezone

LANE_FLASH_BUDGET_USD = 0.25
LANE_FLASH_MAX = 40
LANE_FLASH_PER_LANE = 8
LANE_FLASH_WINDOW_HOURS = 26
LANE_FLASH_BATCH = 20
RECENT_KEEP = 600


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def flashes_enabled(env=None):
    from live import fd_accounts
    env = env if env is not None else os.environ
    return env.get('FD_LANE_FLASHES', '1') != '0' and 'new' in fd_accounts.enabled_groups()


def data_sources_enabled(env=None):
    return (env if env is not None else os.environ).get('FD_LANE_DATA_SOURCES', '1') != '0'


def budget_usd():
    return max(0.0, _env_float('FD_LANE_FLASH_BUDGET_USD', LANE_FLASH_BUDGET_USD))


def _ts(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def gather(state, *, now=None, known=None, fetch=None, window_hours=LANE_FLASH_WINDOW_HOURS, flash_max=None,
           per_lane=None):
    """No model call. Fetch the outlets, drop seen / known / old, dedupe across outlets and against recently
    extracted lane flashes, balance across lanes (round robin, newest first), cap. -> dict(selected, outlets, ...)."""
    from live.adapters import flashes, lane_flashes
    now = now or datetime.now(timezone.utc)
    fetch = fetch or lane_flashes.fetch
    flash_max = int(os.environ.get('FD_LANE_FLASH_MAX', LANE_FLASH_MAX) if flash_max is None else flash_max)
    per_lane = int(os.environ.get('FD_LANE_FLASH_PER_LANE', LANE_FLASH_PER_LANE) if per_lane is None else per_lane)
    st = state.get('lane_flashes') or {}
    seen = set(st.get('seen') or [])
    since = now - timedelta(hours=window_hours)
    gathered, outlets = [], []
    for cid in lane_flashes.OUTLETS:
        row = dict(id=cid, status='ok', items=0, on_lane=0, new=0, error=None)
        try:
            out = fetch(cid, since=since, now=now)
            row.update(status=out.get('status', 'ok'), items=out.get('items', 0), on_lane=len(out.get('sources') or []))
            for src in out.get('sources') or []:
                if src['id'] in seen or (known and (known(src['id']) or (src.get('url') and known(src['url'])))):
                    continue
                gathered.append(src)
                row['new'] += 1
        except Exception as exc:   # noqa: BLE001 - one outlet down never stops the others
            row.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        outlets.append(row)
    recent = [r for r in st.get('recent') or [] if (_ts(r.get('published_at')) or now) >= since]
    kept, dropped = flashes.dedupe(gathered, hours=6, recent=recent)
    by_lane = {}
    for s in sorted(kept, key=lambda s: -(_ts(s.get('published_at')) or now).timestamp()):
        by_lane.setdefault(s['source_id'], []).append(s)
    selected, overflow = [], []
    lanes = sorted(by_lane)
    i = 0
    while any(by_lane.values()):
        lane = lanes[i % len(lanes)]
        i += 1
        if not by_lane[lane]:
            continue
        s = by_lane[lane].pop(0)
        if len(selected) < flash_max and sum(1 for x in selected if x['source_id'] == lane) < per_lane:
            selected.append(s)
        else:
            overflow.append(s)
    return dict(selected=selected, overflow=overflow, dropped=dropped, outlets=outlets,
                by_lane=dict(Counter(s['source_id'] for s in selected)))


def extract(db, selected, *, client, budget, cost_cap_usd, fence_usd, state, now, extract_batch=None,
            batch_size=LANE_FLASH_BATCH):
    """Batched cheap EXTRACT inside the lane ring fence; units tagged with their lane route beats (no Jev).
    -> stats dict."""
    from live import flash_extract, registry, source_routes
    from scripts.run_content_adapters import ingest_batches
    extract_batch = extract_batch or flash_extract.extract_batch
    st = state.setdefault('lane_flashes', {})
    start = budget.spent()
    fence = min(float(cost_cap_usd), start + max(0.0, float(fence_usd)))
    budget.set_cap(fence)
    stats = dict(selected=len(selected), extracted=0, with_units=0, units_added=0, calls=0, prompt_tokens=0,
                 completion_tokens=0, dropped_units=0, failed_flashes=[], budget_usd=float(fence_usd),
                 fence_cap_usd=round(fence, 4), deferred_budget=0, by_lane={})
    seen = set(st.get('seen') or [])
    recent = list(st.get('recent') or [])
    try:
        groups = flash_extract.batches(selected, batch_size)
        for gi, group in enumerate(groups):
            tier = registry.source_licence_tier(group[0]['source_id']) or 'B'
            try:
                result = extract_batch(group, client, licence_tier=tier, stats=stats)
            except budget.BudgetExceeded:
                stats['deferred_budget'] = sum(len(g) for g in groups[gi:])
                break
            stats['extracted'] += len(group)
            for src in group:
                units = result.get(src['id']) or []
                if units:
                    stats['with_units'] += 1
                    added = ingest_batches(db, [(src, units, src['adapter'])], {}, jev=None)['added']
                    db.set_persona_tags(source_routes.tags_for(units, src['source_id']), .7)
                    stats['units_added'] += added
                    stats['by_lane'][src['source_id']] = stats['by_lane'].get(src['source_id'], 0) + added
                seen.add(src['id'])
                recent.append(dict(id=src['id'], text=src['original_text'][:300], published_at=src.get('published_at')))
    finally:
        budget.set_cap(cost_cap_usd)
        st['seen'] = sorted(seen)[-5000:]
        st['recent'] = recent[-RECENT_KEEP:]
        st['last_run'] = now.isoformat()
    stats['cost_usd'] = round(budget.spent() - start, 4)
    stats['failed_flashes'] = len(stats['failed_flashes'])
    return stats


SNAPSHOT_SOURCES_EXTRA = ('polymarket_markets', 'defillama_yields')


# snapshot sources replaced by another source id (all their units go; the newest marker is a sentinel)
RETIRED_SNAPSHOTS = {'defillama_sol_base_tvl': 'defillama_solana / defillama_base',
                     'defillama_sol_base_dex': 'defillama_solana / defillama_base'}


def snapshot_source_ids():
    from live.adapters import lane_data
    return set(lane_data.FETCHERS) | set(SNAPSHOT_SOURCES_EXTRA)


def supersede_snapshots(store_root, source_ids=None):
    """A structured lane source is a daily snapshot: only its newest snapshot stays retrievable, older snapshot units go
    to suppressed.jsonl (reversible; ContentStore drops them on load), so an account never gets yesterday's and today's
    Hyperliquid table as two packets. -> {source_id: units suppressed}."""
    import json
    from pathlib import Path
    root = Path(store_root)
    path = root / 'units.jsonl'
    if not path.exists():
        return {}
    ids = set(source_ids or snapshot_source_ids())
    supp_path = root / 'suppressed.jsonl'
    already = set()
    if supp_path.exists():
        already = {json.loads(l)['unit_id'] for l in supp_path.read_text().splitlines() if l.strip()}
    snaps = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        src = r.get('source') or {}
        if src.get('source_id') in RETIRED_SNAPSHOTS and r['unit_id'] not in already:
            snaps.setdefault(src['source_id'], {}).setdefault(('', None), []).append(r['unit_id'])
            snaps[src['source_id']].setdefault(('~retired', RETIRED_SNAPSHOTS[src['source_id']]), [])
        elif src.get('source_id') in ids and r['unit_id'] not in already:
            snaps.setdefault(src['source_id'], {}).setdefault((str(src.get('published_at') or ''), src.get('id')), []).append(r['unit_id'])
    out, lines = {}, []
    for sid, by in snaps.items():
        newest = max(by)
        old = [u for k, us in by.items() if k != newest for u in us]
        if old:
            out[sid] = len(old)
            lines += [json.dumps({'unit_id': u, 'reason': f'lane snapshot superseded by {newest[1]}'}) for u in old]
    if lines:
        with supp_path.open('a') as fh:
            fh.write('\n'.join(lines) + '\n')
    return out
