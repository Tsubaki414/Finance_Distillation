"""Free daily options-positioning data for trading_shortterm (tier B, deterministic, no model calls).

- cboe_options: Cboe daily market statistics (put/call ratios, SPX put/call volume) - public JSON.
- cboe_vol_extra: VVIX, SKEW and VIX1D closes - public Cboe index histories.
- squeezemetrics: DIX (dark-pool short-volume index) and GEX (dealer gamma exposure) - free public CSV.
Paraphrase-only with attribution; never republish tables.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from live.adapters import common

CBOE_DAILY = 'https://cdn.cboe.com/data/us/options/market_statistics/daily/{}_daily_options'
CBOE_INDEX = 'https://cdn-api.cboe.com/api/global/us_indices/daily_prices/{}_History.csv'
SQUEEZE = 'https://squeezemetrics.com/monitor/static/DIX.csv'
RATIOS = {'TOTAL PUT/CALL RATIO': 'Total', 'EQUITY PUT/CALL RATIO': 'Equity', 'INDEX PUT/CALL RATIO': 'Index',
          'SPX + SPXW PUT/CALL RATIO': 'SPX+SPXW', 'CBOE VOLATILITY INDEX (VIX) PUT/CALL RATIO': 'VIX options'}


def _trading_days_back(today, n):
    d = today
    while n > 0:
        if d.weekday() < 5:
            yield d
            n -= 1
        d -= timedelta(days=1)


def fetch_cboe_options(*, transport=None, today=None, lookback=6):
    """Latest available daily options statistics (walks back over weekends/holidays)."""
    requests = 0
    for d in _trading_days_back(today or date.today(), lookback):
        requests += 1
        st, body = common.http_get(CBOE_DAILY.format(d.isoformat()), transport=transport)
        if st != 200:
            continue
        try:
            data = json.loads(body)
        except ValueError:
            continue
        period = d.isoformat()
        rows = []
        for r in data.get('ratios') or []:
            label = RATIOS.get(r.get('name'))
            if label and str(r.get('value', '')).strip():
                v = str(r['value']).strip()
                rows.append({'line': f'Cboe {label} put/call ratio, {period}: {v}.', 'number': v,
                             'metric': f'{label} put/call ratio', 'period': period})
        for r in data.get('SPX + SPXW') or []:
            if r.get('name') == 'VOLUME' and r.get('put') is not None:
                v = str(r['put'] + r['call'])
                rows.append({'line': f'SPX + SPXW options volume, {period}: {v} contracts.', 'number': v,
                             'metric': 'SPX+SPXW options volume', 'period': period})
        if rows:
            return common.structured_result(rows, id='cboe-options-' + period, source_id='cboe_options_stats',
                                            publisher='Cboe Global Markets', title='Cboe daily options market statistics',
                                            url=CBOE_DAILY.format(period), published_at=period, adapter='options_flow',
                                            requests=requests)
    return {'status': 'no_data', 'requests': requests, 'sources': [], 'units': []}


def _history(body):
    out = []
    for r in csv.DictReader(io.StringIO(body.lstrip('\ufeff'))):
        r = {k.strip().upper(): (v or '').strip() for k, v in r.items() if k}
        close = r.get('CLOSE') or next((v for k, v in r.items() if k not in ('DATE',) and v), '')
        if r.get('DATE') and close:
            out.append((datetime.strptime(r['DATE'], '%m/%d/%Y').date().isoformat(), close))
    return sorted(out)


def fetch_cboe_vol_extra(*, transport=None):
    rows, failures = [], []
    for name, label in (('VVIX', 'VVIX (volatility of VIX)'), ('SKEW', 'Cboe SKEW index'), ('VIX1D', 'VIX1D (1-day VIX)')):
        st, body = common.http_get(CBOE_INDEX.format(name), transport=transport)
        if st != 200:
            failures.append(st)
            continue
        h = _history(body)
        if not h:
            continue
        period, close = h[-1]
        close = format(Decimal(close), '.2f')
        rows.append({'line': f'{label} latest close, {period}: {close}.', 'number': close, 'metric': name + ' close', 'period': period})
        if name == 'VVIX' and len(h) >= 6:
            chg = format(Decimal(h[-1][1]) - Decimal(h[-6][1]), '.2f')
            rows.append({'line': f'VVIX 5-trading-day change, {period}: {chg} points.', 'number': chg,
                         'metric': 'VVIX 5-day change', 'period': period})
    latest = max((r['period'] for r in rows), default='')
    out = common.structured_result(rows, id='cboe-volextra-' + latest, source_id='cboe_indices', publisher='Cboe Global Markets',
                                   title='Cboe VVIX, SKEW and VIX1D', url=CBOE_INDEX.format('VVIX'), published_at=latest,
                                   adapter='options_flow', requests=3)
    if failures:
        out['status'] = 'partial' if rows else f'http_{failures[0]}'
    return out


def _ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def fetch_squeezemetrics(*, transport=None):
    st, body = common.http_get(SQUEEZE, transport=transport)
    if st != 200:
        return {'status': f'http_{st}', 'requests': 1, 'sources': [], 'units': []}
    h = [r for r in csv.DictReader(io.StringIO(body.lstrip('\ufeff'))) if r.get('date') and r.get('dix') and r.get('gex')]
    if not h:
        return {'status': 'no_data', 'requests': 1, 'sources': [], 'units': []}
    last, period = h[-1], h[-1]['date'].strip()
    dix = format(Decimal(last['dix']) * 100, '.1f')
    gex = format(Decimal(last['gex']) / Decimal(1e9), '.2f')
    rows = [{'line': f'SqueezeMetrics DIX (dark-pool short-volume index), {period}: {dix}%.', 'number': dix + '%',
             'metric': 'DIX', 'period': period},
            {'line': f'SqueezeMetrics GEX (estimated dealer gamma exposure), {period}: ${gex} billion per 1% move.',
             'number': '$' + gex + ' billion', 'metric': 'GEX', 'period': period}]
    year = [Decimal(r['gex']) for r in h[-252:]]
    if len(year) >= 60:
        pct = format(Decimal(sum(1 for g in year if g <= Decimal(last['gex']))) / len(year) * 100, '.0f')
        rows.append({'line': f'GEX percentile versus the past year, {period}: {_ordinal(int(pct))} percentile.', 'number': pct,
                     'metric': 'GEX 1-year percentile', 'period': period})
    if len(h) >= 6:
        chg = format((Decimal(last['gex']) - Decimal(h[-6]['gex'])) / Decimal(1e9), '.2f')
        rows.append({'line': f'GEX 5-trading-day change, {period}: ${chg} billion.', 'number': '$' + chg + ' billion',
                     'metric': 'GEX 5-day change', 'period': period})
    return common.structured_result(rows, id='squeezemetrics-' + period, source_id='squeezemetrics_dix',
                                    publisher='SqueezeMetrics', title='SqueezeMetrics DIX and GEX', url=SQUEEZE,
                                    published_at=period, adapter='options_flow', requests=1)


def fetch(*, transport=None):
    """All three, merged into one adapter result (one source per feed)."""
    parts = [fetch_cboe_options(transport=transport), fetch_cboe_vol_extra(transport=transport),
             fetch_squeezemetrics(transport=transport)]
    return {'status': 'ok' if all(p['status'] == 'ok' for p in parts) else ('partial' if any(p['sources'] for p in parts) else parts[0]['status']),
            'requests': sum(p['requests'] for p in parts), 'sources': [s for p in parts for s in p['sources']],
            'units': [u for p in parts for u in p['units']], 'parts': [p['status'] for p in parts]}
