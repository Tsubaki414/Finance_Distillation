"""Remove units (and every sidecar row that references them) from a content store, with a JSON log.

  python scripts/remove_units.py --store live/store/content_units --source-ids ch100_www_omnycontent_com \
      --reason tdm_reserved --log /workspace/x/removed_units_YYYYMMDD.json
Run scripts/backup_live.py first. Removed rows are kept verbatim in the log so they can be restored.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _rows(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def _refs(row, ids):
    return any(isinstance(v, str) and v in ids for v in row.values())


def _write(path, rows):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    os.replace(tmp, path)


def remove_units(store, ids, *, reason, log):
    store = Path(store); ids = set(ids)
    units = _rows(store/'units.jsonl')
    removed = [r for r in units if r.get('unit_id') in ids]
    out = {'at': datetime.now(timezone.utc).isoformat(), 'reason': reason,
           'removed_units': [r['unit_id'] for r in removed], 'rows': removed, 'sidecar_rows': {}}
    if removed:
        found = set(out['removed_units'])
        _write(store/'units.jsonl', [r for r in units if r.get('unit_id') not in found])
        for path in sorted(store.glob('*.jsonl')):
            if path.name == 'units.jsonl': continue
            rows = _rows(path); drop = [r for r in rows if _refs(r, found)]
            if drop:
                out['sidecar_rows'][path.name] = drop
                _write(path, [r for r in rows if not _refs(r, found)])
    Path(log).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--store', type=Path, required=True)
    ap.add_argument('--ids', nargs='*', default=[])
    ap.add_argument('--source-ids', nargs='*', default=[])
    ap.add_argument('--reason', required=True)
    ap.add_argument('--log', type=Path, required=True)
    a = ap.parse_args()
    ids = set(a.ids) | {r['unit_id'] for r in _rows(a.store/'units.jsonl') if (r.get('source') or {}).get('source_id') in set(a.source_ids)}
    r = remove_units(a.store, ids, reason=a.reason, log=a.log)
    print(json.dumps({'removed': len(r['removed_units']), 'sidecars': {k: len(v) for k, v in r['sidecar_rows'].items()}}))


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
