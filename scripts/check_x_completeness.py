"""P0-3a data check: completeness basis for every captured X post (read-only).

Reads raw Apify capture files, normalizes each unique post with the current
rule and reports the basis distribution, every non-complete post with reason,
and a hard check: no complete post may end with an ellipsis.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live.xsearch import normalize_item, ELLIPSIS_TAIL, _core  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('roots', nargs='*', type=Path, default=[
        ROOT / 'runs/account_sources_v1/monitor_captures/zh_macro/x_qinbafrank/raw',
        ROOT / 'runs/account_sources_v1/monitor_captures/zh_industry/x_dylan522p/raw'])
    args = ap.parse_args()
    manifest, report = [], {}
    for root in args.roots:
        seen, basis, holds = {}, Counter(), []
        for path in sorted(p for p in root.glob('*.json') if not p.name.startswith('._')):
            manifest.append({'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            raw = json.loads(path.read_text())
            for i, x in enumerate(raw.get('items', [])):
                row = normalize_item(x, query='check', run_id=raw.get('run_id', ''), dataset_id=raw.get('dataset_id', ''),
                                     fetched_at=raw.get('fetched_at', ''), raw_import_ref=f'{path.name}#items/{i}')
                if row and row['post_id'] not in seen:
                    seen[row['post_id']] = row
        bad = []
        for pid, row in seen.items():
            basis[row['completeness_basis']] += 1
            if row['content_complete'] and ELLIPSIS_TAIL.search(_core(row['original_text'])):
                bad.append(pid)
            if not row['content_complete']:
                holds.append({'post_id': pid, 'basis': row['completeness_basis'],
                              'tail': row['original_text'][-40:]})
        report[str(root.relative_to(ROOT))] = {'unique_posts': len(seen), 'basis': dict(basis),
                                               'not_complete': holds, 'complete_with_ellipsis': bad}
    ok = all(not r['complete_with_ellipsis'] for r in report.values())
    out = {'item': 'P0-3a', 'pass': ok, 'report': report, 'manifest_files': len(manifest),
           'manifest_sha256': hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
