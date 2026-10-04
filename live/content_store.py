"""Shared content store (seed of the shared insights DB).

Append-only JSONL of content units that passed the EXTRACT contract, each with
its licence tier, attribution (publisher / speaker for the frame), source
metadata, the adapter that produced it, and advisory persona routing / Jev
pre-screen. Dedup by unit_id and claim/number content, including near duplicates. Only writable tiers (A quote, B paraphrase) are
stored; C/D never become units.
"""
from __future__ import annotations

import collections
import json
import re
import unicodedata
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


def normalize_claim(value):
    """Ignore case, whitespace, punctuation and numeric presentation in prose.

    Numeric evidence is retained separately, including signs, decimals and units.
    """
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    value = re.sub(r'\d[\d,.]*', ' ', value)
    return ' '.join(''.join(' ' if unicodedata.category(c).startswith('P') else c
                            for c in value).split())


def normalize_number(value):
    value = unicodedata.normalize('NFKC', str(value or '')).casefold().replace('−', '-')
    return re.sub(r'\s+', '', value).replace(',', '')


def content_key(source, unit):
    numbers = tuple(sorted((normalize_number(n.get('text')), ' '.join(str(n.get('period') or '').casefold().split()))
                           for n in unit.get('numbers', [])))
    publisher = ' '.join(str(source.get('publisher') or '').casefold().split())
    speaker = ' '.join(str(unit.get('speaker') or '').casefold().split())
    return normalize_claim(unit.get('statement')), numbers, speaker, publisher


def duplicate_content(first, second):
    a = content_key(first.get('source', {}), first['unit'])
    b = content_key(second.get('source', {}), second['unit'])
    if a == b:
        return True
    if set(a[1]) != set(b[1]) or a[3] != b[3]:
        return False
    x, y = set(a[0].split()), set(b[0].split())
    return bool(x | y) and len(x & y) / len(x | y) >= .8


class ContentStore:
    def __init__(self, root=None):
        self.root = Path(root or ROOT)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'units.jsonl'
        self._rows = {}
        self._licence_overrides = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    self._rows[r['unit_id']] = r

        suppressed = self.root / "suppressed.jsonl"
        if suppressed.exists():
            for line in suppressed.read_text().splitlines():
                if line.strip():
                    self._rows.pop(json.loads(line)["unit_id"], None)

        for row in self._rows.values():
            row['persona_tags'] = {}
            row['tag_personas'] = []
        self._load_sidecars()

    def _load_sidecars(self):
        from live.persona_tags import tagged_personas
        views = {}
        for name in ('persona_tags', 'licence_overrides', 'view_enrich', 'view_normalized', 'freshness'):
            path = self.root / (name + '.jsonl')
            if not path.exists():
                continue
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                row = self._rows.get(entry['unit_id'])
                if row is None:
                    continue
                if name == 'freshness':
                    row['unit'].update({k: entry[k] for k in ('as_of', 'as_of_source', 'date_unknown', 'freshness_flags') if k in entry})
                    row['unit']['published_at_norm'] = entry.get('published_at')
                elif name == 'persona_tags':
                    row['persona_tags'] = entry['tags']
                    row['tag_personas'] = tagged_personas(entry['tags'], entry['threshold'])
                elif name in ('view_enrich', 'view_normalized'):
                    views[entry['unit_id']] = (entry, name == 'view_normalized')
                else:
                    self._licence_overrides[entry['unit_id']] = entry['overrides']
        from live.distillation import ContractError
        self.view_errors = []
        for entry, normalized in views.values():
            try:
                self._apply_view_enrichment(entry, normalized=normalized)
            except ContractError as exc:
                # A stale/invalid sidecar view never blocks loading; the unit keeps its inline view.
                self.view_errors.append({'unit_id': entry.get('unit_id'), 'error': str(exc)[:200]})
        self._rows = {uid: self.apply_licence_overrides(row) for uid, row in self._rows.items()}

    def _apply_view_enrichment(self, entry, *, normalized=False):
        from live.content_units import validate_view
        from live.distillation import require
        row = self._rows.get(entry['unit_id'])
        if row is None:
            return False
        unit = row['unit']
        require(unit.get('kind') == 'view', 'view_enrich: unit must be view')
        structured = validate_view(entry.get('view'), unit.get('source_spans', []),
                                   source_or_unit=row, number_warnings=True)
        row['unit'] = dict(unit, view=structured, view_source='normalized' if normalized else 'enriched')
        return True

    def set_view_enrichments(self, entries):
        """Append validated enrichments; preserve units.jsonl and native v2 views."""
        from live.content_units import validate_view
        from live.distillation import require
        from live.view_enrich import has_valid_view
        added = 0
        with (self.root / 'view_enrich.jsonl').open('a') as fh:
            for entry in entries:
                row = self._rows.get(entry['unit_id'])
                if row is None:
                    continue
                require(row['unit'].get('kind') == 'view', 'view_enrich: unit must be view')
                structured = validate_view(entry.get('view'), row['unit'].get('source_spans', []))
                if has_valid_view(row['unit']):
                    continue
                saved = {key: entry[key] for key in ('unit_id', 'enriched_at', 'model', 'version')}
                saved['view'] = structured
                fh.write(json.dumps(saved, ensure_ascii=False) + '\n')
                self._apply_view_enrichment(saved)
                added += 1
        return added

    def apply_licence_overrides(self, row):
        """Apply only this row's explicit overrides, preserving raw integrity evidence."""
        overrides = self._licence_overrides.get(row.get('unit_id'))
        if not overrides:
            return row
        unit = dict(row.get('unit') or {}, **overrides)
        return dict(row, unit=unit, licence_tier=unit.get('licence_tier'),
                    attribution=dict(row.get('attribution') or {}, usage=unit.get('usage')))

    def set_persona_tags(self, tags_by_uid, threshold=0.7):
        from live.persona_tags import tagged_personas
        if not 0 <= threshold <= 1:
            raise ValueError('threshold must be between zero and one')
        with (self.root / 'persona_tags.jsonl').open('a') as fh:
            for uid, tags in tags_by_uid.items():
                if uid not in self._rows:
                    continue
                personas = tagged_personas(tags, threshold)
                fh.write(json.dumps({'unit_id': uid, 'tags': tags, 'tagged_at': now(),
                                     'threshold': threshold}, ensure_ascii=False) + '\n')
                self._rows[uid].update(persona_tags=tags, tag_personas=personas)

    def untagged(self):
        return [row for row in self._rows.values() if not row.get('persona_tags')]

    def add(self, source, units, *, adapter, personas=None, prescreen=None):
        added = duplicate = duplicate_count = 0
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
                if any(duplicate_content(row, rec) for row in self._rows.values()):
                    duplicate_count += 1
                    continue
                fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
                self._rows[u['unit_id']] = dict(rec, persona_tags={}, tag_personas=[])
                added += 1
        return {'added': added, 'duplicate': duplicate, 'duplicate_content': duplicate_count}

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
