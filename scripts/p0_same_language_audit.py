"""P0-1 acceptance: re-run admission over the stored inbox (read-only).

The store is append-only; historical same-language rows stay. The check is that
none of them can still be admitted, i.e. none can be regenerated or approved.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live.account_intelligence import Store, DEFAULT, account
from live.account_sources import admission


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--store', type=Path, default=DEFAULT)
    args = ap.parse_args()
    store = Store(args.store)
    rows = store.rows('inbox')
    same = [r for r in rows if r.get('source_language') == account(r['account_id'])['language']]
    still = []
    for r in same:
        source = store.get('sources', r['source_id'])
        if admission(r['account_id'], source)['admitted']:
            still.append(r['id'])
    report = {'item': 'P0-1', 'inbox_rows': len(rows), 'same_language_rows': len(same),
              'same_language_by_source': dict(Counter(r['canonical_source_id'] for r in same)),
              'same_language_still_admitted': still,
              'pass': not still}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
