"""Report and suppress existing content duplicates without altering units.jsonl."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.content_store import ContentStore, content_key
from live.distillation_source import now


def dedup_store(root):
    """Same result as comparing every unit with every earlier kept unit via duplicate_content, but keys are computed
    once and only units with the same number set + publisher are compared (duplicate_content is False otherwise).
    Oct 10: the all-pairs version (re-normalising both claims per pair) took 6-10 CPU-min on 5.4k units and stalled
    the nightly."""
    store = ContentStore(root)
    buckets, duplicates = {}, []
    for row in store.units():
        key = content_key(row.get('source', {}), row['unit'])
        words = set(key[0].split())
        bucket = buckets.setdefault((frozenset(key[1]), key[3]), [])
        first = next((r for k, w, r in bucket
                      if k == key or (bool(w | words) and len(w & words) / len(w | words) >= .8)), None)
        if first:
            duplicates.append({'unit_id': row['unit_id'], 'kept_unit_id': first['unit_id'],
                               'reason': 'duplicate_content', 'suppressed_at': now()})
        else:
            bucket.append((key, words, row))
    with (store.root / 'suppressed.jsonl').open('a') as f:
        for row in duplicates:
            f.write(json.dumps(row) + '\n')
    return duplicates


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--store', type=Path, required=True)
    ap.add_argument('--report', action='store_true')
    args = ap.parse_args()
    rows = dedup_store(args.store)
    print(json.dumps({'duplicates': rows, 'suppressed': len(rows)}, indent=2))

if __name__ == '__main__': main()
