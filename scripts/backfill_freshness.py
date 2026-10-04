#!/usr/bin/env python3
"""Derive observation dates. Dry run by default; only --write changes a sidecar."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.freshness import derive_dates


def read_rows(store):
    # Deliberately avoid ContentStore's directory-creation behavior in read-only tools.
    rows = {}
    with (Path(store) / 'units.jsonl').open() as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                rows[row['unit_id']] = row
    return list(rows.values())


def backfill(store, write=False):
    entries = [dict(unit_id=r['unit_id'], **derive_dates(r)) for r in read_rows(store)]
    if write:
        root = Path(store)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=root, prefix='.freshness-', suffix='.tmp', delete=False) as fh:
                temp = fh.name
                for entry in entries:
                    fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp, root / 'freshness.jsonl')
        finally:
            if temp and Path(temp).exists():
                Path(temp).unlink()
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    entries = backfill(args.store, args.write)
    from scripts.freshness_report import build_report
    report = build_report(args.store)
    report['sidecar_written'] = args.write
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'units': len(entries), **report['coverage'], 'sidecar_written': args.write}, ensure_ascii=False))


if __name__ == '__main__':
    main()
