"""Farside spot ETF flows, US$m; missing observations remain unknown."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from live.adapters import common

URLS = {'BTC': 'https://farside.co.uk/bitcoin-etf-flow-all-data/',
        'ETH': 'https://farside.co.uk/ethereum-etf-flow-all-data/'}


def flow_value(value):
    value = value.strip().replace(',', '')
    if value in ('', '-', '–', '—'):
        return None
    return Decimal('-' + value[1:-1] if value.startswith('(') and value.endswith(')') else value)


def parse_table(body):
    headers, rows = [], []
    for block in re.findall(r'<tr\b[^>]*>(.*?)</tr>', body, re.S | re.I):
        cells = [common.html_text(c) for c in re.findall(r'<t[dh]\b[^>]*>(.*?)</t[dh]>', block, re.S | re.I)]
        if not cells:
            continue
        if cells[-1] == 'Total' and not headers:
            headers = cells[1:] if cells[0] in ('Date', '') else cells
            continue
        try:
            period = datetime.strptime(cells[0], '%d %b %Y').date().isoformat()
        except ValueError:
            continue
        if not headers or len(cells) != len(headers) + 1:
            continue
        values = dict(zip(headers, map(flow_value, cells[1:])))
        total = values.pop('Total')
        if total is not None:
            rows.append({'date': period, 'funds': values, 'total': total})
    return sorted(rows, key=lambda r: r['date'])


def fetch(*, transport=None):
    sources, units, failures = [], [], []
    for asset, url in URLS.items():
        st, body = common.http_get(url, transport=transport)
        if st != 200:
            failures.append(st)
            continue
        days = parse_table(body)[-5:]
        if not days:
            continue
        rows = []
        for day in days:
            number, period = format(day['total'], '.1f'), day['date']
            note = ' (reported total; fund data incomplete)' if None in day['funds'].values() else ''
            rows.append({'line': f'{asset} spot ETF total net flow, {period}: {number} US$m{note}.',
                         'number': number, 'metric': asset + ' ETF net flow', 'period': period})
        period = days[0]['date'] + ' to ' + days[-1]['date']
        number = format(sum(d['total'] for d in days), '.1f')
        rows.append({'line': f'{asset} spot ETF {len(days)}-trading-day sum of reported totals, {period}: {number} US$m.',
                     'number': number, 'metric': asset + ' ETF 5-day sum', 'period': period})
        funds = [(k, v) for k, v in days[-1]['funds'].items() if v is not None]
        if funds:
            fund, value = max(funds, key=lambda kv: abs(kv[1]))
            number, period = format(value, '.1f'), days[-1]['date']
            rows.append({'line': f'{asset} largest reported single-fund flow by magnitude ({fund}), {period}: {number} US$m.',
                         'number': number, 'metric': asset + ' largest fund flow', 'period': period})
        out = common.structured_result(rows, id='farside-' + asset.lower() + '-' + days[-1]['date'],
                                       source_id='farside_etf_flows', publisher='Farside Investors', title=asset + ' spot ETF flows',
                                       url=url, published_at=days[-1]['date'], adapter='farside')
        sources += out['sources']
        units += out['units']
    return {'status': ('partial' if failures else 'ok') if sources else (f'http_{failures[0]}' if failures else 'no_data'),
            'requests': 2, 'sources': sources, 'units': units}
