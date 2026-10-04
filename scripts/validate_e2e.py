#!/usr/bin/env python3
"""Report offline shared-store coverage and integrity; validation failures exit 0."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live import content_units
from live.content_store import ContentStore, ROOT
from live.jev_front import PERSONAS
from live.reportgem_daily import RATING
from live.retrieval import units_for_persona


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def check_row(row):
    """Return categorized failures; re-run the extraction number contract verbatim."""
    failures = []
    def fail(category, reason):
        failures.append((category, reason))
    unit, source = row.get('unit') or {}, row.get('source') or {}
    attribution = row.get('attribution') or {}
    if row.get('licence_tier') not in ('A', 'B') or unit.get('licence_tier') not in ('A', 'B'):
        fail('non_writable_tiers', 'record/unit licence tier is not A or B')
    elif row['licence_tier'] != unit['licence_tier']:
        fail('non_writable_tiers', 'record and unit licence tiers disagree')
    if not any(_nonempty(attribution.get(k)) for k in ('publisher', 'speaker')):
        fail('missing_attribution', 'attribution must name the original publisher or speaker')
    reportgem = source.get('adapter') == 'reportgem'
    names = [attribution.get(k) for k in ('publisher', 'speaker')]
    if reportgem:
        if any('reportgem' in str(n).replace(' ', '').casefold() for n in names if n):
            fail('reportgem_attributed_to_reportgem', 'ReportGem is a distributor, not the originating bank')
        bank = source.get('publisher')
        if not _nonempty(bank) or 'reportgem' in bank.replace(' ', '').casefold() or not any(
                _nonempty(n) and n.strip().casefold() == bank.strip().casefold() for n in names):
            fail('missing_attribution', 'ReportGem attribution does not name the source bank')
    for key in ('source_id', 'published_at', 'source_hash'):
        if not _nonempty(source.get(key)):
            fail('missing_provenance', f'source missing {key}')
        if unit.get(key) is not None and unit[key] != source.get(key):
            fail('missing_provenance', f'unit/source {key} disagree')
    # A report ID plus adapter identifies an offline source even without a URL.
    if not (source.get('url') or source.get('provenance') or row.get('provenance') or
            (source.get('adapter') and source.get('id'))):
        fail('missing_provenance', 'source missing url or provenance (adapter + source document id)')
    if not _nonempty(unit.get('statement')):
        fail('broken_bindings', 'unit missing statement')
    spans = unit.get('source_spans')
    if not isinstance(spans, list) or not spans:
        fail('broken_bindings', 'unit missing cited source spans')
        spans = []
    for i, span in enumerate(spans):
        if not isinstance(span, dict) or not _nonempty(span.get('exact_text')):
            fail('broken_bindings', f'span {i}: missing exact_text')
        elif span.get('source_hash') is not None and span['source_hash'] != source.get('source_hash'):
            fail('broken_bindings', f'span {i}: source_hash disagrees with source')
    numbers = unit.get('numbers')
    if not isinstance(numbers, list):
        fail('broken_bindings', 'numbers must be a list')
    else:
        for i, number in enumerate(numbers):
            try:
                content_units._number(number, spans, f'number {i}')
            except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
                fail('broken_bindings', str(exc))
    if row.get('unit_id') != unit.get('unit_id') or not _nonempty(row.get('unit_id')):
        fail('broken_bindings', 'record/unit unit_id missing or inconsistent')
    text = '\n'.join([str(unit.get('statement') or '')] +
                     [str(s.get('exact_text') or '') for s in spans if isinstance(s, dict)])
    if RATING.search(text):
        fail('ratings_targets', 'rating/price target found in statement or cited evidence (reportgem_daily.RATING)')
    return failures


def validate_store(store, minimum=8):
    # Read raw rows: ContentStore deduplication would conceal repeated JSONL IDs.
    raw = [json.loads(line) for line in store.path.read_text().splitlines() if line.strip()]
    categories = ('non_writable_tiers', 'missing_attribution', 'broken_bindings', 'missing_provenance',
                  'duplicate_unit_ids', 'reportgem_attributed_to_reportgem', 'ratings_targets')
    checks = {name: [] for name in categories}
    failures_by_id = {}
    for row in raw:
        uid = row.get('unit_id')
        for category, reason in check_row(row):
            failure = {'unit_id': uid, 'reason': reason}
            checks[category].append(failure)
            failures_by_id.setdefault(uid, []).append(failure)
    for uid, count in Counter(r.get('unit_id') for r in raw).items():
        if count > 1:
            failure = {'unit_id': uid, 'reason': f'duplicate unit_id occurs {count} times'}
            checks['duplicate_unit_ids'].append(failure)
            failures_by_id.setdefault(uid, []).append(failure)
    personas = {}
    for persona in PERSONAS:
        served = units_for_persona(store, persona)
        failures = [failure for r in served for failure in failures_by_id.get(r['unit_id'], [])]
        personas[persona] = {
            'routed_count': sum(r['match'] == 'routed' for r in served),
            'keyword_matched_count': sum(r['match'] == 'keyword' for r in served),
            'total_served': len(served),
            'by_adapter': dict(Counter(r['source'].get('adapter') for r in served)),
            'by_tier': dict(Counter(r.get('licence_tier') for r in served)),
            'integrity_failures': failures,
            'status': 'PASS' if len(served) >= minimum and not failures else 'FAIL'}
    return {'store': str(store.root), 'minimum': minimum, 'raw_rows': len(raw),
            'unique_units': len(store.units()), 'personas': personas, 'global_checks': checks,
            'status': 'PASS' if all(p['status'] == 'PASS' for p in personas.values()) and not any(checks.values()) else 'FAIL',
            'limitations': ['Keyword retrieval establishes beat matches, not semantic editorial suitability.',
                            'Number bindings are checked against stored cited evidence using content_units._number; original documents are not fetched.',
                            'Source provenance accepts a URL, explicit provenance, or adapter plus document id. Source hashes are checked for presence/consistency, not recomputed without original text.']}


def render_markdown(report):
    if 'error' in report:
        return f"Validation could not complete: {report['error']}\n"
    lines = [f"E2E validation: **{report['status']}**. {report['unique_units']} unique units; minimum {report['minimum']} per persona.", '',
             '| Persona | Routed | Keyword | Served | Adapters | Tiers | Integrity failures | Result |',
             '| --- | ---: | ---: | ---: | --- | --- | ---: | --- |']
    for persona, p in report['personas'].items():
        counts = lambda values: ', '.join(f'{k}: {v}' for k, v in sorted(values.items(), key=lambda x: str(x[0])))
        lines.append(f"| {persona} | {p['routed_count']} | {p['keyword_matched_count']} | {p['total_served']} | {counts(p['by_adapter'])} | {counts(p['by_tier'])} | {len(p['integrity_failures'])} | {p['status']} |")
    lines += ['', 'Global checks:', '']
    for category, failures in report['global_checks'].items():
        lines.append(f'- {category}: {len(failures)}')
        for failure in failures:
            lines.append(f"  - {failure['unit_id']}: {failure['reason']}")
    lines += ['', *report['limitations'], '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, default=ROOT)
    parser.add_argument('--min', type=int, default=8, dest='minimum')
    parser.add_argument('--out-json', type=Path)
    parser.add_argument('--out-md', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.minimum < 0:
            raise ValueError('--min must be nonnegative')
        if not (args.store / 'units.jsonl').is_file():
            raise ValueError(f'No units.jsonl at {args.store}')
        report = validate_store(ContentStore(args.store), args.minimum)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        report = {'status': 'FAIL', 'error': str(exc), 'store': str(args.store)}
    markdown = render_markdown(report)
    for path, contents in ((args.out_json, json.dumps(report, ensure_ascii=False, indent=2) + '\n'),
                           (args.out_md, markdown)):
        if path:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents)
            except OSError as exc:
                print(f'Could not write {path}: {exc}', file=sys.stderr)
    print(markdown)
    return 0


if __name__ == '__main__':
    sys.exit(main())
