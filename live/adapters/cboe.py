"""Cboe daily volatility index histories (tier B)."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal

from live.adapters import common

API = 'https://cdn-api.cboe.com/api/global/us_indices/daily_prices/{}_History.csv'


def parse_history(body):
    return sorted([(datetime.strptime(r['DATE'].strip(), '%m/%d/%Y').date().isoformat(), r['CLOSE'].strip())
                   for r in csv.DictReader(io.StringIO(body.lstrip('\ufeff'))) if r.get('CLOSE', '').strip()], key=lambda r: r[0])


def fetch(*, transport=None):
    histories, rows = {}, []
    failures = []
    for name in ('VIX', 'VIX9D', 'VIX3M'):
        st, body = common.http_get(API.format(name), transport=transport)
        if st != 200:
            failures.append(st)
            continue
        history = parse_history(body)
        if not history:
            continue
        histories[name] = history
        period, number = history[-1]
        rows.append({'line': f'{name} latest close, {period}: {number}.', 'number': number,
                     'metric': name + ' close', 'period': period})
    vix = histories.get('VIX', [])
    if len(vix) >= 6:
        period = vix[-1][0]
        number = format(Decimal(vix[-1][1]) - Decimal(vix[-6][1]), '.2f')
        rows.append({'line': f'VIX 5-trading-day change, {period}: {number} index points.',
                     'number': number, 'metric': 'VIX 5-day change', 'period': period})
    vix3m = dict(histories.get('VIX3M', []))
    if vix and vix[-1][0] in vix3m and Decimal(vix3m[vix[-1][0]]) != 0:
        period = vix[-1][0]
        ratio = Decimal(vix[-1][1]) / Decimal(vix3m[period])
        number = format(ratio, '.4f')
        state = 'contango' if ratio < 1 else ('backwardation' if ratio > 1 else 'flat')
        rows.append({'line': f'VIX/VIX3M term-structure ratio, {period}: {number} ({state}).',
                     'number': number, 'metric': 'VIX/VIX3M ratio', 'period': period})
    latest = max((r['period'] for r in rows), default='')
    out = common.structured_result(rows, id='cboe-indices-' + latest, source_id='cboe_indices', publisher='Cboe Global Markets',
                                   title='Cboe volatility indices', url=API.format('VIX'), published_at=latest, adapter='cboe', requests=3)
    if failures:
        out['status'] = 'partial' if rows else f'http_{failures[0]}'
    return out
