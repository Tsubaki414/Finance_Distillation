#!/usr/bin/env python3
"""Append no-reproduction overrides without rewriting the shared units file."""
import argparse
import json
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.content_store import ContentStore
from live.distillation_source import now
from live.licence_rules import OVERRIDES


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--source-ids', nargs='+', required=True)
    args = parser.parse_args(argv)
    store = ContentStore(args.store)
    rows = [r for r in store.units() if r['source'].get('source_id') in args.source_ids]
    with (store.root / 'licence_overrides.jsonl').open('a') as fh:
        for row in rows:
            fh.write(json.dumps({'unit_id': row['unit_id'], 'overrides': OVERRIDES,
                                 'overridden_at': now()}) + '\n')
    print(json.dumps({'overridden': len(rows)}))
    return 0

if __name__ == '__main__':
    sys.exit(main())
