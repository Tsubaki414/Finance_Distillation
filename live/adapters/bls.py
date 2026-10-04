"""BLS public API v1 (no key; tier A). Series -> deterministic content units."""
from __future__ import annotations

import json
from datetime import date

from live.adapters import common

SERIES = {'LNS14000000': ('Unemployment rate', 'unemployment rate', '{v} percent'),
          'CES0000000001': ('Total nonfarm payroll employment (thousands)', 'nonfarm payrolls', '{v} thousand'),
          'CUSR0000SA0': ('CPI-U all items index (seasonally adjusted)', 'CPI index', '{v}'),
          'CES0500000003': ('Average hourly earnings, total private', 'average hourly earnings', '${v}')}
API = 'https://api.bls.gov/publicAPI/v1/timeseries/data/'


def to_source_and_units(response, *, latest_only=True):
    rows = []
    for s in response['Results']['series']:
        label, metric, fmt = SERIES.get(s['seriesID'], (s['seriesID'], s['seriesID'], '{v}'))
        for d in s['data'][:1 if latest_only else None]:
            period = f'{d["periodName"]} {d["year"]}'
            number = fmt.format(v=d['value'])
            rows.append({'line': f'{label} (BLS series {s["seriesID"]}), {period}: {number}.',
                         'number': number, 'metric': metric, 'period': period, 'year': d['year']})
    text = '\n\n'.join(r['line'] for r in rows)
    latest = max((r['period'] for r in rows), default='')
    src = common.make_source(id='bls-' + common.digest(text)[:12], source_id='primary_bls',
                             text=text, publisher='U.S. Bureau of Labor Statistics', title='BLS series, latest ' + latest,
                             url=API + ','.join(s['seriesID'] for s in response['Results']['series']),
                             published_at=date.today().isoformat(), adapter='bls_api')
    return src, common.data_units(src, rows, speaker='U.S. Bureau of Labor Statistics')


def fetch(series=tuple(SERIES), *, transport=None):
    out_sources = []
    responses = []
    for sid in series:
        st, body = common.http_get(API + sid, transport=transport)
        if st == 200:
            data = json.loads(body)
            if data.get('status') == 'REQUEST_SUCCEEDED':
                responses.extend(data['Results']['series'])
    if not responses:
        return {'status': 'no_data', 'sources': [], 'units': []}
    src, units = to_source_and_units({'Results': {'series': responses}})
    return {'status': 'ok', 'sources': [src], 'units': units, 'requests': len(series)}
