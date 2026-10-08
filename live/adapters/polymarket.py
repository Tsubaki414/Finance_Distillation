"""Polymarket public market data (Oct 8, 36 accounts: prediction-market lane). Tier B, structured, no model call.

One read-only GET to the public Gamma API (no key, no login, no cookies): open events ordered by 24h volume. Each kept
event becomes one dated line with its leading outcome's last price and the event's 24h volume. Sports and
tweet-count events are left out (no betting promos; the prediction accounts read news through the odds).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from live.adapters import common

API = 'https://gamma-api.polymarket.com/events'
SOURCE_ID = 'polymarket_markets'
SKIP_TAGS = {'sports', 'nfl', 'nba', 'mlb', 'nhl', 'soccer', 'tennis', 'golf', 'esports', 'mma', 'boxing', 'cricket',
             'tweet-markets', 'mentions', 'pop-culture', 'awards', 'entertainment'}


def _money(x):
    x = float(x or 0)
    return f'${x / 1e6:.1f}m' if x >= 1e6 else f'${x / 1e3:.0f}k'


def leading(event):
    """(question, outcome label, price 0-1) of the event's leading market outcome, or None."""
    best = None
    for m in event.get('markets') or []:
        if m.get('closed') or not m.get('active', True):
            continue
        try:
            outcomes, prices = json.loads(m.get('outcomes') or '[]'), [float(p) for p in json.loads(m.get('outcomePrices') or '[]')]
        except (TypeError, ValueError):
            continue
        if not outcomes or len(outcomes) != len(prices):
            continue
        if outcomes[:2] == ['Yes', 'No']:
            cand = (m.get('groupItemTitle') or m.get('question') or '', 'Yes', prices[0])
        else:
            i = max(range(len(prices)), key=prices.__getitem__)
            cand = (m.get('question') or '', outcomes[i], prices[i])
        if 0.0 < cand[2] < 1.0 and (best is None or cand[2] > best[2]):
            best = cand
    return best


def fetch(*, limit=8, transport=None, now=None):
    st, body = common.http_get(API + '?order=volume24hr&ascending=false&closed=false&limit=40', transport=transport)
    if st != 200:
        return {'status': f'http_{st}', 'requests': 1, 'sources': [], 'units': []}
    now = now or datetime.now(timezone.utc)
    period = now.date().isoformat()
    rows = []
    for e in json.loads(body):
        tags = {str(t.get('slug') or t.get('label') or '').lower() for t in e.get('tags') or [] if isinstance(t, dict)}
        if tags & SKIP_TAGS or 'tweets' in str(e.get('title') or '').lower():
            continue
        lead = leading(e)
        if not lead or not e.get('volume24hr'):
            continue
        question, outcome, price = lead
        pct, vol = f'{price * 100:.0f}%', _money(e['volume24hr'])
        title = ' '.join(str(e.get('title') or '').split())[:140]
        q = ' '.join(str(question).split())[:140]
        what = f'"{outcome}" on "{q}"' if q and q != title else f'"{outcome}"'
        rows.append({'line': f'Polymarket "{title}", {period}: {what} trades at {pct}; 24h volume {vol}.',
                     'metric': 'Polymarket implied probability', 'period': period, 'number': pct,
                     'numbers': [{'text': pct, 'metric': 'Polymarket implied probability', 'period': period, 'span_ref': 0},
                                 {'text': vol, 'metric': 'Polymarket 24h volume', 'period': period, 'span_ref': 0}]})
        if len(rows) >= limit:
            break
    return common.structured_result(rows, id=f'{SOURCE_ID}-{period}', source_id=SOURCE_ID, publisher='Polymarket',
                                    title='Polymarket: most-traded open markets (24h volume)', url=f'{API}#{period}',
                                    published_at=period, adapter='polymarket')
