#!/usr/bin/env python3
"""Derive observation dates. Dry run by default; only --write changes a sidecar."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import re
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.freshness import derive_dates, normalize_date


def read_rows(store):
    # Deliberately avoid ContentStore's directory-creation behavior in read-only tools.
    rows = {}
    with (Path(store) / 'units.jsonl').open() as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                rows[row['unit_id']] = row
    return list(rows.values())


def recover_published_at(row, cached_sources=None):
    """Recover dates from URL paths and local cache only; never fetch a feed."""
    source = dict(row.get('source') or {})
    if normalize_date(source.get('published_at')):
        return row
    # A valid but future date is evidence, not a missing date to replace.
    if source.get('published_at') not in (None, '', 'T00:00:00Z'):
        return row
    candidates = []
    match = re.search(r'(\d{4})[-/](\d{2})[-/](\d{2})', source.get('url') or '')
    if match:
        candidates.append('-'.join(match.groups()))
    def visit(value):
        if isinstance(value, list):
            for item in value: visit(item)
        elif isinstance(value, dict):
            if any(source.get(k) and source[k] == value.get(k) for k in ('id', 'url', 'source_hash')):
                candidates.extend(value.get(k) for k in ('published_at', 'pubDate', 'date', 'published', 'published_raw'))
                candidates.extend((value.get('metadata') or {}).get(k) for k in ('published_at','pubDate'))
            for item in value.values():
                if isinstance(item, (dict,list)): visit(item)
    for root in cached_sources or []:
        root = Path(root)
        paths = [root] if root.is_file() else list(root.rglob('*.json')) + list(root.rglob('*.xml')) + list(root.rglob('*.rss'))
        for path in paths:
            try:
                if path.suffix == '.json': visit(json.loads(path.read_text()))
                else:
                    for item in ET.parse(path).getroot().iter('item'):
                        links = [item.findtext('link'), item.findtext('guid')]
                        links.extend(node.get('url') for node in item.iter() if node.tag.split('}')[-1] == 'transcript')
                        if any(source.get(k) and source[k] in links for k in ('url','id')):
                            candidates.append(item.findtext('pubDate'))
            except (ValueError, OSError, ET.ParseError):
                continue
    for raw in candidates:
        value = normalize_date(raw)
        if not value and raw:
            try: value = normalize_date(parsedate_to_datetime(raw).date().isoformat())
            except (TypeError, ValueError, OverflowError): pass
        if value:
            source['published_at'] = value
            unit = dict(row.get('unit') or {})
            if unit.get('published_at') in (None, '', 'T00:00:00Z'): unit['published_at'] = value
            return dict(row, source=source, unit=unit)
    return row


def backfill(store, write=False, cached_sources=None):
    entries = [dict(unit_id=r['unit_id'], **derive_dates(recover_published_at(r, cached_sources))) for r in read_rows(store)]
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
    parser.add_argument('--cached-sources', type=Path, nargs='*', default=[Path('/workspace/x/sources_live')])
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    entries = backfill(args.store, args.write, args.cached_sources)
    from scripts.freshness_report import build_report
    report = build_report(args.store)
    report['sidecar_written'] = args.write
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'units': len(entries), **report['coverage'], 'sidecar_written': args.write}, ensure_ascii=False))


if __name__ == '__main__':
    main()
