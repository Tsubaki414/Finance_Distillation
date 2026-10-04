"""Report and suppress existing content duplicates without altering units.jsonl."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.content_store import ContentStore, duplicate_content
from live.distillation_source import now


def dedup_store(root):
    store = ContentStore(root)
    kept, duplicates = [], []
    for row in store.units():
        first = next((r for r in kept if duplicate_content(r, row)), None)
        if first:
            duplicates.append({'unit_id': row['unit_id'], 'kept_unit_id': first['unit_id'],
                               'reason': 'duplicate_content', 'suppressed_at': now()})
        else:
            kept.append(row)
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
