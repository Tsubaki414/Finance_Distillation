"""P0-3c data check (read-only): verify every Morris inbox source still blocked
on body completeness, using the current archive verification rule."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live.account_intelligence import Store  # noqa: E402
from live.archive_verification import verify_archive_row  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--store', type=Path, required=True)
    args = ap.parse_args()
    store = Store(args.store)
    rows = [r for r in store.rows('inbox') if r['account_id'] == 'en_morris_archive'
            and 'Original text completeness unverified' in r.get('blocking_gaps', [])]
    seen, results = set(), []
    for r in rows:
        src = store.get('sources', r['source_id'])
        if src['id'] in seen:
            continue
        seen.add(src['id'])
        out = verify_archive_row({**src, 'content_complete': False})
        v = out['archive_verification']
        results.append({'source_id': src['id'], 'url': src.get('url'), 'status': v['status'],
                        'evidence': v.get('evidence'), 'basis': v.get('basis'), 'reason': v.get('reason')})
    report = {'item': 'P0-3c', 'inbox_rows': len(rows), 'unique_sources': len(results),
              'status': dict(Counter(x['status'] for x in results)),
              'by_evidence': dict(Counter(f"{x['evidence']}|{x['status']}" for x in results)),
              'reasons': dict(Counter(x['reason'] for x in results if x['reason'])),
              'rows': results}
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
