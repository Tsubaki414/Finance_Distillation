"""Ingest budget ordering under a fixed cost cap (Oct 6 v8).

05:21 run on 2026-10-06 hit the $8 cap after 9 opus extractions; 58 items were deferred (The Block,
CoinDesk, Unchained, Ritholtz, AWOCS, Futurum, Moontower, ...) and crypto_macro_zh/en got 0 new
units, because the static channel `priority()` always put the same CN/edgar channels first. With
the cap unchanged, the extract order now is:

  0. pre-extracted batches (units already provided by the adapter: no LLM extract cost);
  1. fair-share floor: personas sorted by fewest fresh units, round-robin `floor` items each,
     items deferred by the previous run first inside each persona;
  2. everything else: previous-run deferred first, then personas with fewer fresh units, then the
     legacy channel priority, then the channel rank.

Previous-run deferred items also bypass `per_channel_max` at gather so they are not dropped again.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNKNOWN = '_unmapped'
_PREFIX = re.compile(r'^(newsletters|rss_fulltext|podcast|x|feed):')


def _split(hint):
    if not hint:
        return []
    if isinstance(hint, (list, tuple)):
        return [h for x in hint for h in _split(x)]
    return [h.strip() for h in re.split(r'[/,|]', str(hint)) if h.strip()]


@lru_cache(maxsize=1)
def _hint_table():
    table = {}
    channels = json.loads((ROOT / 'live/channels.json').read_text()).get('channels') or []
    for c in channels:
        table[c['channel_id']] = _split(c.get('persona_hint'))
    for s in json.loads((ROOT / 'live/source_registry.json').read_text()).get('sources') or []:
        hints = _split(s.get('persona_hints') or s.get('persona_hint'))
        if hints:
            table.setdefault(s['id'], hints)
    known = {h for hs in table.values() for h in hs if '_' in h}
    # bare 'macro' / 'crypto' family hints -> drop unless they are real persona ids
    return {k: [h for h in v if h in known] for k, v in table.items()}


@lru_cache(maxsize=1)
def _store_personas(store=str(ROOT / 'live/store/content_units')):
    """source_id -> personas its stored units were tagged for (fallback for unhinted newsletters)."""
    path = Path(store) / 'units.jsonl'
    counts = {}
    if not path.exists():
        return {}
    # v9: persona_tags relevance (relevant=1, tangential=0.4, x confidence) beats the unit's single
    # `personas` label (libertystreet: one article labelled investing_philosophy; tags say macro_rates_en).
    tags = {}
    tag_path = Path(store) / 'persona_tags.jsonl'
    if tag_path.exists():
        with tag_path.open() as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                tags[row.get('unit_id')] = row.get('tags') or {}
    weighted = {}
    with path.open() as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            sid = (row.get('source') or {}).get('source_id') or (row.get('unit') or {}).get('source_id')
            ps = row.get('tag_personas') or row.get('personas') or []
            if sid and ps:
                counts.setdefault(sid, Counter()).update(ps)
            for persona, t in (tags.get(row.get('unit_id')) or {}).items():
                w = {'relevant': 1.0, 'tangential': 0.4}.get((t or {}).get('verdict'), 0) * float((t or {}).get('confidence') or 0)
                if sid and w:
                    weighted.setdefault(sid, Counter())[persona] += w
    out = {}
    for sid, c in weighted.items():
        top = c.most_common(2)
        out[sid] = [p for p, v in top if v >= 0.5 * top[0][1]]
    for sid, c in counts.items():
        if sid in out:
            continue
        total = sum(c.values())
        out[sid] = [p for p, n in c.most_common(3) if n / total >= 0.2]
    return out


def channel_personas(channel_id, source=None):
    """Personas a channel/source feeds. Hints from channels.json / source_registry.json, then the
    persona tags of that source's stored units; [UNKNOWN] when nothing is known."""
    table = _hint_table()
    cid = str(channel_id or '')
    bare = _PREFIX.sub('', cid)
    for key in (cid, bare, str((source or {}).get('source_id') or ''), bare + '_research'):
        if key and table.get(key):
            return list(table[key])
    stored = _store_personas()
    for key in (str((source or {}).get('source_id') or ''), bare):
        if key and stored.get(key):
            return list(stored[key])
    return [UNKNOWN]


def previous_deferred(runs_dir, *, before=None):
    """Deferred items of the newest daily summary (YYYYMMDD.json) strictly before `before` (YYYYMMDD)."""
    runs = sorted(p for p in Path(runs_dir).glob('[0-9]' * 8 + '.json') if not before or p.stem < before)
    for path in reversed(runs):   # a dry-run / locked summary deferred nothing: skip it, keep the backlog
        try:
            data = json.loads(path.read_text())
        except ValueError:
            continue
        if data.get('status') in ('dry_run', 'locked', 'backup_failed'):
            continue
        items = list(data.get('deferred') or [])
        return {'run': path.name, 'ids': {d['id'] for d in items if d.get('id')},
                'channels': Counter(d.get('channel') for d in items), 'items': items}
    return {'run': None, 'ids': set(), 'channels': Counter(), 'items': []}


def _keys(source):
    return {str(source.get(k)) for k in ('id', 'url', 'source_hash') if source.get(k)}


def order_tasks(tasks, fresh_by_persona, deferred_ids=(), *, floor=2, legacy_priority=None):
    """Return (ordered_tasks, plan). task = (channel_dict, source, units, adapter, keys, rank).

    `plan` rows explain each position: phase, persona charged, prior-deferred flag."""
    fresh = dict(fresh_by_persona or {})
    deferred_ids = set(deferred_ids or ())
    legacy = legacy_priority or (lambda channel, source: 3)

    def info(task):
        ch, s = task[0], task[1]
        ps = channel_personas(ch['id'], s)
        known = [p for p in ps if p != UNKNOWN]
        neediest = min(known, key=lambda p: (fresh.get(p, 0), p)) if known else UNKNOWN
        need = fresh.get(neediest, 0) if known else 10 ** 6
        prior = bool(deferred_ids & (_keys(s) | set(task[4] or ())))
        return dict(persona=neediest, personas=ps, need=need, prior=prior,
                    legacy=legacy(ch['id'], s), rank=task[5])

    meta = [info(t) for t in tasks]
    idx = list(range(len(tasks)))
    free = [i for i in idx if tasks[i][2] is not None]            # phase 0: no extract cost
    paid = [i for i in idx if tasks[i][2] is None]
    within = lambda i: (not meta[i]['prior'], meta[i]['legacy'], meta[i]['rank'], i)
    by_persona = {}
    for i in sorted(paid, key=within):
        by_persona.setdefault(meta[i]['persona'], []).append(i)
    personas = sorted((p for p in by_persona if p != UNKNOWN), key=lambda p: (fresh.get(p, 0), p))
    floor_order, taken = [], set()
    if not fresh:   # no freshness report (fresh store / failed report): legacy channel priority only
        floor = 0
        for m in meta:
            m['need'] = 0
    for rnd in range(max(0, int(floor))):
        for p in personas:
            queue = [i for i in by_persona[p] if i not in taken]
            if queue:
                floor_order.append(queue[0]); taken.add(queue[0])
    rest = sorted((i for i in paid if i not in taken),
                  key=lambda i: (not meta[i]['prior'], meta[i]['need'], meta[i]['legacy'], meta[i]['rank'], i))
    order, plan = [], []
    for phase, block in (('pre_extracted', free), ('fair_share_floor', floor_order), ('rest', rest)):
        for i in block:
            order.append(tasks[i])
            plan.append(dict(phase=phase, channel=tasks[i][0]['id'], id=tasks[i][1].get('id'),
                             persona=meta[i]['persona'], personas=meta[i]['personas'],
                             fresh=meta[i]['need'] if meta[i]['persona'] != UNKNOWN else None,
                             prior_deferred=meta[i]['prior']))
    return order, plan
