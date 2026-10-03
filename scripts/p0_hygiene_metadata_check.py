"""P0-3d data check (read-only): which stored hygiene calls were metadata-only.

For every stored run whose attempt sent a source_hygiene request, re-classify
the annotations it sent with the current rule and count how many requests would
now need no model call (all annotations resolved metadata).
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live import source_hygiene as hygiene  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--store', type=Path, required=True)
    ap.add_argument('--focus', nargs='*', default=[])
    args = ap.parse_args()
    total, avoided, fields, focus = 0, 0, Counter(), {}
    for path in sorted((args.store / 'runs').glob('run-*.json')):
        run = json.loads(path.read_text())
        attempt = (run.get('source_adaptation') or {}).get('attempt') or {}
        annotations = attempt.get('hygiene_annotations')
        if not annotations or 'source_hygiene' not in (attempt.get('stage_calls') or {}):
            continue
        total += 1
        judged = [a for a in annotations if not hygiene.resolved_metadata(a)]
        for a in annotations:
            fields[(a.get('kind'), (a.get('metadata') or {}).get('field'), hygiene.resolved_metadata(a))] += 1
        if not judged:
            avoided += 1
        if any(run['id'].startswith(f) for f in args.focus):
            focus[run['id']] = {'annotations': len(annotations), 'still_judged': len(judged),
                                'judged_kinds': sorted({a['kind'] for a in judged})}
    out = {'item': 'P0-3d', 'runs_with_hygiene_call': total, 'would_need_no_model_call': avoided,
           'annotation_kinds': {f'{k}|{f}|resolved={r}': n for (k, f, r), n in fields.most_common()},
           'focus_runs': focus}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
