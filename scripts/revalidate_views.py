#!/usr/bin/env python3
"""Offline view revalidation; optionally save normalized views in a sidecar."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live.content_units import DIRECTIONS, HORIZONS, locate, validate_view
from live.distillation import ContractError


def _entries(path):
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                yield json.loads(line)


def _strict_valid(view, spans):
    """The previous contract, retained only for migration statistics."""
    if not isinstance(view, dict):
        return False
    if (view.get('direction') not in DIRECTIONS or
            view.get('conviction') not in ('low', 'medium', 'high') or
            view.get('horizon') not in HORIZONS):
        return False
    if not isinstance(view.get('subject'), str) or not view['subject'].strip():
        return False
    reasons = view.get('reasoning')
    if not isinstance(reasons, list) or not 1 <= len(reasons) <= 3:
        return False
    for reason in reasons:
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
            return False
        if not any(locate(span['exact_text'], reason)[0] >= 0 for span in spans):
            return False
    return ('conditions' not in view or
            isinstance(view['conditions'], str) and bool(view['conditions'].strip()))


def revalidate_views(store, *, write=False):
    root = Path(store)
    # Read without validating so rejected sidecars become report entries.
    rows = {r['unit_id']: r for r in _entries(root / 'units.jsonl')}
    for entry in _entries(root / 'suppressed.jsonl'):
        rows.pop(entry['unit_id'], None)
    for name in ('view_enrich', 'view_normalized'):
        for entry in _entries(root / (name + '.jsonl')):
            if entry['unit_id'] in rows:
                rows[entry['unit_id']]['unit']['view'] = entry.get('view')
    report = dict(total=0, valid_before=0, valid_after=0, coerced=0,
                  rejected_with_reasons=[], rejection_counts={})
    normalized = []
    for uid, row in rows.items():
        unit = row['unit']
        if unit.get('kind') != 'view':
            continue
        report['total'] += 1
        spans = unit.get('source_spans', [])
        proposed = unit.get('view')
        report['valid_before'] += int(_strict_valid(proposed, spans))
        try:
            view = validate_view(proposed, spans)
        except ContractError as exc:
            report['rejected_with_reasons'].append(dict(unit_id=uid, reason=str(exc)))
            continue
        report['valid_after'] += 1
        report['coerced'] += int(bool(view.get('coerced')))
        normalized.append(dict(unit_id=uid, view=view))
    report['rejection_counts'] = dict(Counter(e['reason'] for e in report['rejected_with_reasons']))
    if write:
        path = root / 'view_normalized.jsonl'
        # Replace atomically so reruns do not retain obsolete normalized views.
        temporary = root / 'view_normalized.jsonl.tmp'
        temporary.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in normalized))
        temporary.replace(path)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, default=Path('live/store/content_units'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    report = revalidate_views(args.store, write=args.write)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'rejected_with_reasons'}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
