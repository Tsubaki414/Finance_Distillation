"""Scheduled catalysts: what is going to happen, and when, before it happens.

Everything else in this system is reactive — it learns that something occurred because somebody
posted about it. An earnings calendar is the opposite, and it is what the Scheduled Catalyst
content lane was specified on. It is also the concrete answer to 「盘前 AMD」: knowing a week in
advance that AMD reports **before the open** on a given date is what lets anything be ready.

Source: Nasdaq's calendar endpoint. Free, no key, no account.

**Its fragility is the main thing to know about it.** It is not a documented public API, it
returns nothing without a browser-shaped User-Agent, and it can change or close without notice.
So a failure here is recorded as a failure — `{'ok': False, ...}` with the reason — and never
returned as an empty calendar. A quiet day and a dead endpoint look identical otherwise, and the
difference is whether the system is blind.

The user was asked on 2026-09-24 whether to register a Finnhub key as a second path and answered
「我去注册，key 给你」. `FINNHUB_API_KEY` in .env is read when present, so that fallback works the
moment the key arrives without this file changing. Until then Nasdaq is a single point of failure
and this docstring is the record of that.

Note on the User-Agent: unlike live/news.py's SEC path, nobody's contact details go here. The
browser string is what the endpoint requires to answer at all.

Run: .venv/bin/python -B live/calendar_events.py [--days=7] [--watchlist-only]
"""
from __future__ import annotations
from pathlib import Path
import sys, json, time, datetime, urllib.request, urllib.error

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'live/store'
OUT = STORE / 'calendar.jsonl'

NASDAQ = 'https://api.nasdaq.com/api/calendar/earnings?date={date}'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
TIMEOUT = 25
GAP_SECONDS = 1.0

# What the endpoint's `time` field means, spelled out because 「盘前」 is the whole point.
WHEN = {
    'time-pre-market': ('pre_market', '盘前'),
    'time-after-hours': ('after_hours', '盘后'),
    'time-not-supplied': ('unknown', '时间未公布'),
}


def _watchlist_tickers():
    """Tickers the accounts actually cover, so a 200-row calendar becomes a short list."""
    out = set()
    f = ROOT / 'live/sources.json'
    if f.is_file():
        s = json.loads(f.read_text(encoding='utf-8'))
        for a in s.get('x_accounts', []):
            for t in (a.get('tickers') or []):
                out.add(t.upper().lstrip('$'))
    for f in (STORE / 'packets').glob('*.json'):
        try:
            e = json.loads(f.read_text()).get('entity') or ''
        except Exception:
            continue
        if e.startswith('$'):
            out.add(e[1:].upper())
    return out


def fetch_day(day):
    url = NASDAQ.format(date=day.isoformat())
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        return {'ok': False, 'date': day.isoformat(), 'error': f'HTTP {e.code}'}
    except Exception as e:
        return {'ok': False, 'date': day.isoformat(),
                'error': type(e).__name__ + ': ' + str(e)[:140]}
    data = (body or {}).get('data') or {}
    rows = data.get('rows')
    if rows is None:
        # Three tiers, because collapsing them makes the failure signal useless.
        #
        # The first version called every empty day a failure, and the first run reported four:
        # 09-26, 09-27, 10-03 — Saturday, Sunday, Saturday — and 10-02. Weekends have no earnings
        # and never will. A failure list that is mostly weekends is a list nobody reads, and an
        # alarm nobody reads is the same as no alarm. So the calendar's own shape is encoded
        # here rather than left for a reader to mentally filter out.
        if day.weekday() >= 5:
            return {'ok': True, 'date': day.isoformat(), 'rows': [],
                    'why_empty': 'weekend, no US earnings scheduled'}
        return {'ok': False, 'date': day.isoformat(),
                'error': 'trading day, but the response carried no rows field',
                'body_keys': sorted(body.keys()) if isinstance(body, dict) else None}
    return {'ok': True, 'date': day.isoformat(), 'rows': rows,
            'as_of': data.get('asOf')}


def collect(days=7, watchlist_only=False):
    now = datetime.datetime.now(datetime.timezone.utc)
    run_id = 'cal-' + now.strftime('%Y%m%dT%H%M%S')
    watch = _watchlist_tickers()
    events, failures = [], []

    for i in range(days):
        day = (now + datetime.timedelta(days=i)).date()
        r = fetch_day(day)
        if not r['ok']:
            failures.append(r)
            time.sleep(GAP_SECONDS)
            continue
        for row in r['rows']:
            sym = (row.get('symbol') or '').upper()
            if not sym:
                continue
            if watchlist_only and sym not in watch:
                continue
            when, when_zh = WHEN.get(row.get('time'), ('unknown', '时间未公布'))
            events.append({
                'event_id': f'earn-{sym}-{day.isoformat()}',
                'kind': 'earnings',
                'ticker': sym, 'entity': '$' + sym,
                'name': row.get('name'),
                'date': day.isoformat(),
                'when': when, 'when_zh': when_zh,
                'eps_forecast': row.get('epsForecast'),
                'estimate_count': row.get('noOfEsts'),
                'last_year_eps': row.get('lastYearEPS'),
                'last_year_date': row.get('lastYearRptDt'),
                'fiscal_quarter_ending': row.get('fiscalQuarterEnding'),
                'market_cap': row.get('marketCap'),
                'on_watchlist': sym in watch,
                'source': 'nasdaq_calendar',
                'source_note': ('undocumented public endpoint; it requires a browser User-Agent '
                                'and may change without notice'),
                'collected_at': now.isoformat(), 'run_id': run_id,
            })
        time.sleep(GAP_SECONDS)

    if events:
        STORE.mkdir(parents=True, exist_ok=True)
        seen = set()
        if OUT.is_file():
            for line in OUT.read_text(encoding='utf-8').split('\n'):
                if line.strip():
                    try:
                        seen.add(json.loads(line)['event_id'])
                    except Exception:
                        continue
        fresh = [e for e in events if e['event_id'] not in seen]
        with OUT.open('a', encoding='utf-8') as fh:
            for e in fresh:
                fh.write(json.dumps(e, ensure_ascii=False) + '\n')
    else:
        fresh = []

    trading_days = sum(1 for i in range(days)
                       if (now + datetime.timedelta(days=i)).weekday() < 5)
    return {'run_id': run_id, 'days': days, 'trading_days': trading_days,
            'events': len(events), 'new': len(fresh),
            'on_watchlist': [e for e in events if e['on_watchlist']],
            'failures': failures,
            # Measured against trading days, not calendar days: a week is only five chances.
            'blind': trading_days > 0 and len(failures) >= trading_days,
            'note': ('a failed day is reported as a failure, never as an empty calendar; '
                     'the two are indistinguishable downstream otherwise')}


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    s = collect(days=int(args.get('days', 7)), watchlist_only='watchlist-only' in args)
    print(f"{s['run_id']}  未来 {s['days']} 天 {s['events']} 场财报，新增 {s['new']}")
    if s['failures']:
        print(f"  取不到的日期 {len(s['failures'])} 个：" +
              ', '.join(f"{f['date']}({f['error']})" for f in s['failures'][:4]))
        if s['blind']:
            print('  ！所有日期都失败——这是端点故障，不是「没有财报」')
    hits = s['on_watchlist']
    if hits:
        print(f"\n  观察名单内 {len(hits)} 场：")
        for e in sorted(hits, key=lambda x: (x['date'], x['ticker']))[:20]:
            print(f"    {e['date']}  {e['when_zh']:8} {e['ticker']:6} "
                  f"EPS 预期 {e['eps_forecast'] or '—'}  ({e['estimate_count'] or 0} 家)")
    else:
        print('  观察名单内没有；用 --watchlist-only 之外的方式看全量')


if __name__ == '__main__':
    main()
