"""DefiLlama USD-pegged stablecoin circulating supply (tier B)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from live.adapters import common

API = 'https://stablecoins.llama.fi/stablecoincharts/all'


def fetch(*, transport=None):
    st, body = common.http_get(API, transport=transport)
    if st != 200:
        return {'status': f'http_{st}', 'requests': 1, 'sources': [], 'units': []}
    data = sorted(json.loads(body), key=lambda d: int(d['date']))
    rows, period = [], ''
    if data:
        latest = data[-1]
        timestamp = int(latest['date'])
        period = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
        supply = Decimal(str(latest['totalCirculatingUSD']['peggedUSD']))
        number = f'${supply / Decimal(10**9):.1f}bn'
        rows.append({'line': f'USD-pegged stablecoin circulating supply, {period}: {number}.',
                     'number': number, 'metric': 'USD-pegged stablecoin supply', 'period': period})
        for days in (7, 30):
            prior = [d for d in data if int(d['date']) <= timestamp - days * 86400]
            if not prior:
                continue
            base = Decimal(str(prior[-1]['totalCirculatingUSD']['peggedUSD']))
            if not base:
                continue
            change = supply - base
            amount = f'${change / Decimal(10**9):.1f}bn'
            percent = f'{change / base * 100:.2f}%'
            number = f'{amount} ({percent})'
            base_date = datetime.fromtimestamp(int(prior[-1]['date']), timezone.utc).date().isoformat()
            rows.append({'line': f'USD-pegged stablecoin supply {days}-day change, {period} (baseline {base_date}): {number}.',
                         'number': number, 'metric': f'stablecoin {days}-day change', 'period': period,
                         'numbers': [{'text': value, 'metric': f'stablecoin {days}-day change', 'period': period, 'span_ref': 0}
                                     for value in (amount, percent)]})
    return common.structured_result(rows, id='defillama-stablecoins-' + period, source_id='defillama_stablecoins',
                                    publisher='DefiLlama', title='USD-pegged stablecoin supply', url=API,
                                    published_at=period, adapter='defillama')
