"""Shared content store (seed of the shared insights DB).

Append-only JSONL of content units that passed the EXTRACT contract, each with
its licence tier, attribution (publisher / speaker for the frame), source
metadata, the adapter that produced it, and advisory persona routing / Jev
pre-screen. Dedup by unit_id. Only writable tiers (A quote, B paraphrase) are
stored; C/D never become units.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

from live.distillation_source import now

ROOT = Path(__file__).resolve().parent / 'store' / 'content_units'
WRITABLE = ('A', 'B')
SOURCE_KEYS = ('id', 'source_id', 'publisher', 'author_name', 'title', 'url', 'published_at', 'source_hash',
               'adapter', 'truncated', 'source_language')


def attribution(source, unit):
    from live import attribution_frame
    fields = attribution_frame._fields(source, speaker=unit.get('speaker'))
    return {'publisher': fields['publisher'] or source.get('publisher'), 'speaker': unit.get('speaker'),
            'speaker_type': unit.get('speaker_type'), 'usage': unit.get('usage')}


class ContentStore:
    def __init__(self, root=None):
        self.root = Path(root or ROOT)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'units.jsonl'
        self._rows = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    self._rows[r['unit_id']] = r

    def add(self, source, units, *, adapter, personas=None, prescreen=None):
        added = duplicate = 0
        with self.path.open('a') as fh:
            for u in units:
                if u.get('licence_tier') not in WRITABLE:
                    raise ValueError(f'unit {u.get("unit_id")}: tier {u.get("licence_tier")!r} is not writable')
                if u['unit_id'] in self._rows:
                    duplicate += 1
                    continue
                rec = {'unit_id': u['unit_id'], 'unit': u, 'licence_tier': u['licence_tier'],
                       'attribution': attribution(source, u),
                       'source': {**{k: source.get(k) for k in SOURCE_KEYS}, 'adapter': adapter},
                       'personas': list((personas or {}).get(u['unit_id'], [])),
                       'prescreen': (prescreen or {}).get(u['unit_id']), 'stored_at': now()}
                fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
                self._rows[u['unit_id']] = rec
                added += 1
        return {'added': added, 'duplicate': duplicate}

    def units(self, *, persona=None, tier=None, adapter=None):
        return [r for r in self._rows.values()
                if (persona is None or persona in r['personas']) and (tier is None or r['licence_tier'] == tier)
                and (adapter is None or r['source']['adapter'] == adapter)]

    def stats(self):
        rows = list(self._rows.values())
        return {'units': len(rows),
                'by_tier': dict(collections.Counter(r['licence_tier'] for r in rows)),
                'by_adapter': dict(collections.Counter(r['source']['adapter'] for r in rows)),
                'by_persona': dict(collections.Counter(p for r in rows for p in r['personas'])),
                'sources': len({r['source']['source_hash'] for r in rows})}
