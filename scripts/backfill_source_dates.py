#!/usr/bin/env python3
"""Recover missing/malformed source published_at into the source_dates.jsonl sidecar.

Finds stored sources (by source_id prefix) whose published_at is missing or malformed, fetches each
page once (GBK aware), reads its labelled date (channels.page_date), else a date in the URL.
Dry run by default (prints the table); only --write appends to source_dates.jsonl. units.jsonl is
never rewritten. Run backfill_freshness.py --write afterwards so freshness picks the dates up.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.adapters import common
from live.adapters.channels import _date, page_date
from live.content_store import load_source_dates
from live.distillation_source import now

DEFAULT_STORE = Path(__file__).resolve().parents[1] / 'live' / 'store' / 'content_units'
DEFAULT_PREFIX = 'ch008_stock_finance_sina_com_cn'


def decode_page(body):
    """Bytes -> text: declared meta charset first, then strict UTF-8, then GB18030 (a GBK superset)."""
    if isinstance(body, str):
        return body
    match = re.search(rb'charset\s*=\s*["\']?([A-Za-z0-9_-]+)', body[:4096])
    charset = match[1].decode('ascii').lower() if match else ''
    if charset in ('gbk', 'gb2312', 'gb18030'):
        charset = 'gb18030'
    if charset:
        try:
            return body.decode(charset)
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        return body.decode('utf-8')
    except UnicodeDecodeError:
        return body.decode('gb18030', 'replace')


def missing_sources(store, prefix):
    """Distinct stored sources (by source id) under prefix with no valid published_at and no sidecar date."""
    by_key, by_url = load_source_dates(store)
    found = {}
    with (Path(store) / 'units.jsonl').open() as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            source = row.get('source') or {}
            if not str(source.get('source_id') or '').startswith(prefix):
                continue
            if common.iso_published(source.get('published_at')):
                continue
            entry = by_key.get(source.get('id')) or by_url.get(source.get('url'))
            if entry and common.iso_published(entry.get('published_at')):
                continue
            item = found.setdefault(source.get('id'), {'source_key': source.get('id'), 'url': source.get('url'),
                                                       'stored': source.get('published_at'), 'units': 0})
            item['units'] += 1
    return list(found.values())


def recover(sources, *, transport=None, gap=1.0, sleep=time.sleep):
    pages, results = {}, []
    for item in sources:
        url = item['url'] or ''
        published, method, status = '', 'not_found', None
        if url and url not in pages:
            if pages:
                sleep(gap)
            try:
                status, body = common.http_get(url, transport=transport, binary=True)
                pages[url] = (status, decode_page(body) if status == 200 else '')
            except Exception as exc:  # a failed fetch is reported, never fatal
                pages[url] = (f'{type(exc).__name__}', '')
        if url:
            status, page = pages[url]
            published = page_date(page)
            method = 'page_date' if published else method
        if not published:
            published = _date(url)
            method = 'url_date' if published else method
        results.append(dict(item, published_at=published or None, method=method, http=status))
    return results


def write_sidecar(store, results):
    rows = [{'source_key': r['source_key'], 'url': r['url'], 'published_at': r['published_at'],
             'method': r['method'], 'recovered_at': now()} for r in results if r['published_at']]
    if rows:
        with (Path(store) / 'source_dates.jsonl').open('a') as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    return len(rows)


def table(results):
    lines = ['| source_key | units | stored | http | published_at | method |', '|---|---:|---|---|---|---|']
    for r in results:
        lines.append(f"| {r['source_key']} | {r['units']} | {r['stored']!r} | {r['http']} | {r['published_at']} | {r['method']} |")
    return '\n'.join(lines)


def main(argv=None, *, transport=None, sleep=time.sleep):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--store', type=Path, default=DEFAULT_STORE)
    parser.add_argument('--source-prefix', default=DEFAULT_PREFIX)
    parser.add_argument('--gap', type=float, default=1.0, help='seconds between page fetches')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    results = recover(missing_sources(args.store, args.source_prefix), transport=transport, gap=args.gap, sleep=sleep)
    print(table(results))
    written = write_sidecar(args.store, results) if args.write else 0
    print(json.dumps({'sources': len(results), 'units': sum(r['units'] for r in results),
                      'recovered': sum(1 for r in results if r['published_at']),
                      'sidecar_rows_written': written, 'write': args.write}, ensure_ascii=False))
    return results


if __name__ == '__main__':
    main()
