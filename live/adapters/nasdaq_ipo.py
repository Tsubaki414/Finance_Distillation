"""Nasdaq IPO calendar (Oct 8, 36 accounts: IPO lane). Tier B, structured, no model call.

One read-only GET per run to the public Nasdaq calendar JSON (no key, no login): this month's priced and upcoming US
IPOs (company, ticker, exchange, price or range, deal size, date). Hong Kong listings come from the X sources of the
IPO account; HKEXnews has no stable public JSON, so it is not scraped.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from live.adapters import common

API = 'https://api.nasdaq.com/api/ipo/calendar'
SOURCE_ID = 'nasdaq_ipo_calendar'
# Nasdaq stalls on bot-looking agents; same browser-style UA as live/calendar_events.py
from live.calendar_events import UA  # noqa: E402
HEADERS = {'Accept': 'application/json', 'User-Agent': UA}


def _date(mdy):
    try:
        return datetime.strptime(mdy, '%m/%d/%Y').date().isoformat()
    except (TypeError, ValueError):
        return None


def fetch(*, limit=10, transport=None, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        st, body = common.http_get(f'{API}?date={now:%Y-%m}', headers=HEADERS, transport=transport, timeout=20)
    except Exception as exc:   # noqa: BLE001  (timeouts: the day goes on without the calendar)
        return {'status': f'error {type(exc).__name__}', 'requests': 1, 'sources': [], 'units': []}
    if st != 200:
        return {'status': f'http_{st}', 'requests': 1, 'sources': [], 'units': []}
    data = (json.loads(body) or {}).get('data') or {}
    rows = []
    priced = ((data.get('priced') or {}).get('rows') or [])
    upcoming = (((data.get('upcoming') or {}).get('upcomingTable') or {}).get('rows') or [])
    for kind, items, date_key in (('priced', priced, 'pricedDate'), ('upcoming', upcoming, 'expectedPriceDate')):
        for r in items:
            day = _date(r.get(date_key))
            size = str(r.get('dollarValueOfSharesOffered') or '').strip()
            price = str(r.get('proposedSharePrice') or '').strip()
            name = ' '.join(str(r.get('companyName') or '').split())
            if not (day and size and name):
                continue
            tick = str(r.get('proposedTickerSymbol') or '').strip()
            px = f'${price}' if price else 'no price yet'
            if kind == 'priced':
                line = f'US IPO priced {day}: {name} ({tick}, {r.get("proposedExchange")}) at {px} per share, deal size {size}.'
            else:
                line = f'US IPO expected to price {day}: {name} ({tick}, {r.get("proposedExchange")}), range {px} per share, deal size {size}.'
            rows.append({'line': line, 'number': size, 'metric': f'{name} IPO deal size', 'period': day})
            if len(rows) >= limit:
                break
    return common.structured_result(rows, id=f'{SOURCE_ID}-{now:%Y-%m-%d}', source_id=SOURCE_ID, publisher='Nasdaq',
                                    title=f'US IPO calendar {now:%Y-%m}', url=API, published_at=now.date().isoformat(),
                                    adapter='nasdaq_ipo')
