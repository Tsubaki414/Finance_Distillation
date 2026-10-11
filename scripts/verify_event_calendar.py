#!/usr/bin/env python3
"""Verify live/event_calendar.json: every event's date must appear in its verify.url page (Oct 11 anniversary source).

For a Wikipedia URL the parsed article HTML (MediaWiki API action=parse) minus the reference list / citation
markers / Retrieved-Archived stamps is checked (citations carry access dates that would verify anything); other URLs are fetched as HTML and
stripped. A date counts when it appears in one of the usual spellings (3 January 2009 / January 3, 2009 / 2009-01-03,
"Jan." ...) or as day + month with the year within 160 characters (near_match). Sets verify.status = ok | date_not_found | fetch_error, verify.checked_at and
verify.match (the matched spelling); live/anniversary.py uses only status "ok" events.
verify.method manual_webfetch (checked by hand through a fetch tool when the site blocks scripts; the quote is in
verify.match) is kept as is; price_extreme (cycle highs / lows) checks the date of the extreme in exchange data
(Binance daily klines / Yahoo daily) between verify.from and verify.to.

  python3 scripts/verify_event_calendar.py [--only id1,id2] [--dry-run]
Network only; no model calls. Raw pages are cached under /tmp/fd_event_verify (not in git).
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / 'live' / 'event_calendar.json'
CACHE = Path('/tmp/fd_event_verify')
UA = 'fd-event-calendar-verify/1.0 (research; contact via repo)'


def spellings(d):
    m, ms = calendar.month_name[d.month], calendar.month_abbr[d.month]
    return [f'{d.day} {m} {d.year}', f'{m} {d.day}, {d.year}', f'{m} {d.day} {d.year}', d.isoformat(),
            f'{d.day} {ms} {d.year}', f'{ms} {d.day}, {d.year}', f'{ms}. {d.day}, {d.year}', f'{d.day}th {m} {d.year}',
            f'{m} {d.day}th, {d.year}', f'{m} {d.day}st, {d.year}', f'{m} {d.day}nd, {d.year}', f'{m} {d.day}rd, {d.year}',
            f'{d.year}/{d.month:02d}/{d.day:02d}', f'{d.year}年{d.month}月{d.day}日']


def near_match(low, d, span=160):
    """'12 January' / 'January 12' (word-bounded) with the year within `span` chars: prose like "On 12 January,
    ... in 2009" or "in 2012 ... on November 28". Returns the matched snippet or None."""
    m = calendar.month_name[d.month].lower()
    rx = re.compile(rf'(?<![\d\w])(?:{d.day}(?:st|nd|rd|th)?\s+{m}|{m}\s+{d.day}(?:st|nd|rd|th)?)(?![\d])')
    for hit in rx.finditer(low):
        win = low[max(0, hit.start() - span):hit.end() + span]
        if re.search(rf'(?<!\d){d.year}(?!\d)', win):
            return 'near: ' + low[max(0, hit.start() - 40):hit.end() + 40].strip()
    return None


def fetch(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / (hashlib.sha1(url.encode()).hexdigest() + '.txt')
    if p.exists() and time.time() - p.stat().st_mtime < 86400:
        return p.read_text()
    u = urllib.parse.urlparse(url)
    if u.netloc.endswith('wikipedia.org') and u.path.startswith('/wiki/'):
        title = urllib.parse.unquote(u.path[len('/wiki/'):])
        api = (f'https://{u.netloc}/w/api.php?action=parse&prop=text&redirects=1&format=json&formatversion=2&page='
               + urllib.parse.quote(title))
        data = json.loads(urllib.request.urlopen(urllib.request.Request(api, headers={'User-Agent': UA}), timeout=30).read())
        raw = data['parse']['text']
        # article prose + infobox only: citations carry access / archive dates that would "verify" anything
        raw = re.sub(r'<ol class="references".*?</ol>', ' ', raw, flags=re.S)
        raw = re.sub(r'<sup[^>]*class="reference".*?</sup>', ' ', raw, flags=re.S)
        raw = re.sub(r'<(style|script)[^>]*>.*?</\1>', ' ', raw, flags=re.S)
        text = html.unescape(re.sub(r'<[^>]+>', ' ', raw))
        text = re.sub(r'(?:Retrieved|Archived from the original on|accessed)\s+[^.]{0,40}\d{4}', ' ', text)
    else:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30).read()
        text = html.unescape(re.sub(r'<[^>]+>', ' ', raw.decode('utf-8', 'replace')))
    text = re.sub(r'\s+', ' ', text)
    p.write_text(text)
    return text


def price_extreme(spec, getter=None):
    """Date (ISO) of the max high / min low / min close of `symbol` between from and to (daily bars, UTC)."""
    t0 = int(datetime.fromisoformat(spec['from']).replace(tzinfo=timezone.utc).timestamp())
    t1 = int(datetime.fromisoformat(spec['to']).replace(tzinfo=timezone.utc).timestamp()) + 86399
    get = getter or (lambda url: json.loads(urllib.request.urlopen(urllib.request.Request(
        url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30).read()))
    rows = []
    if spec['provider'] == 'binance':
        start = t0 * 1000
        while start < t1 * 1000:
            data = get(f"https://data-api.binance.vision/api/v3/klines?symbol={spec['symbol']}&interval=1d"
                       f"&startTime={start}&endTime={t1 * 1000}&limit=1000")
            if not data:
                break
            rows += [(k[0] // 1000, float(k[2]), float(k[3]), float(k[4])) for k in data]
            start = data[-1][0] + 86400000
    else:
        sym = urllib.parse.quote(spec['symbol'])
        res = get(f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={t0}&period2={t1}&interval=1d')
        r = res['chart']['result'][0]
        q = r['indicators']['quote'][0]
        rows = [(t, h, l, c) for t, h, l, c in zip(r['timestamp'], q['high'], q['low'], q['close']) if None not in (h, l, c)]
    if not rows:
        return None, None
    key = {'max': (max, 1), 'min': (min, 2), 'min_close': (min, 3)}[spec['extreme']]
    best = key[0](rows, key=lambda x: x[key[1]])
    return datetime.fromtimestamp(best[0], timezone.utc).date().isoformat(), best[key[1]]


def check(ev, fetch_fn=fetch):
    d = date.fromisoformat(ev['date'])
    if ev.get('verify', {}).get('method') == 'manual_webfetch':
        return {k: v for k, v in ev['verify'].items() if k in ('status', 'url', 'match')}
    if ev.get('verify', {}).get('method') == 'price_extreme':
        try:
            when, value = price_extreme(ev['verify'])
        except Exception as exc:   # noqa: BLE001
            return {'status': 'fetch_error', 'url': ev['verify']['url'], 'errors': [f'{type(exc).__name__}: {exc}'[:120]]}
        ok = when == ev['date']
        return {'status': 'ok' if ok else 'date_not_found', 'url': ev['verify']['url'],
                'match': f"{ev['verify']['extreme']} {ev['verify']['symbol']} {value} on {when}"}
    urls = [ev['verify']['url']] + [s['url'] for s in ev.get('sources') or [] if s['url'] != ev['verify']['url']]
    errors = []
    for url in urls:
        try:
            text = fetch_fn(url)
        except Exception as exc:   # noqa: BLE001
            errors.append(f'{url}: {type(exc).__name__}: {str(exc)[:80]}')
            continue
        low = text.lower()
        for s in spellings(d):
            if s.lower() in low:
                return {'status': 'ok', 'url': url, 'match': s}
        near = near_match(low, d)
        if near:
            return {'status': 'ok', 'url': url, 'match': near}
    return {'status': 'fetch_error' if errors and len(errors) == len(urls) else 'date_not_found',
            'url': ev['verify']['url'], **({'errors': errors} if errors else {})}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--path', type=Path, default=CAL)
    a = ap.parse_args()
    cal = json.loads(a.path.read_text())
    only = {x for x in a.only.split(',') if x}
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    bad = []
    for ev in cal['events']:
        if only and ev['id'] not in only:
            continue
        res = check(ev)
        ev['verify'] = {**{k: v for k, v in ev['verify'].items() if k not in ('status', 'match', 'errors', 'checked_at')},
                        **res, 'url': res.get('url') or ev['verify']['url'], 'checked_at': now}
        print(f"{res['status']:15} {ev['date']} {ev['id']:26} {res.get('match') or ''}")
        if res['status'] != 'ok':
            bad.append(ev['id'])
        time.sleep(0.3)
    if not a.dry_run:
        a.path.write_text(json.dumps(cal, ensure_ascii=False, indent=1) + '\n')
    print(f"{len(cal['events'])} events, not ok: {bad}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
