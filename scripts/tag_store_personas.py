#!/usr/bin/env python3
"""Review shared-store units against every persona and append semantic tags."""
import argparse
import json
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.content_store import ContentStore
from live.persona_tags import tag_units
from live.retrieval import counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--jev-run', type=Path, required=True)
    parser.add_argument('--threshold', type=float, default=.7)
    parser.add_argument('--max-calls', type=int)
    parser.add_argument('--only-untagged', action='store_true')
    args = parser.parse_args(argv)
    from live.jev_review_client import JevReviewClient
    from ml import budget as spend
    spend.STORE = args.jev_run / 'ledger'
    spend.LEDGER = spend.STORE / 'spend.json'
    store = ContentStore(args.store)
    stats = {}
    tags = tag_units(store.untagged() if args.only_untagged else store.units(),
                     jev=JevReviewClient(args.jev_run), threshold=args.threshold,
                     max_calls=args.max_calls, stats=stats)
    store.set_persona_tags(tags, args.threshold)
    print(json.dumps({'tagged_counts': counts(store)['by_persona'], 'stats': stats}, sort_keys=True))
    return 0

if __name__ == '__main__':
    sys.exit(main())
