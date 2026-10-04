"""U.S. Treasury Fiscal Data API (no key; tier A, primary_treasury) -> deterministic units."""
from __future__ import annotations

import json

from live.adapters import common

API = ('https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates'
       '?sort=-record_date&page%5Bsize%5D=12')


def to_source_and_units(data, *, securities=('Treasury Bills', 'Treasury Notes', 'Treasury Bonds')):
    latest = max(d['record_date'] for d in data['data'])
    rows = []
    for d in data['data']:
        if d['record_date'] == latest and d['security_desc'] in securities:
            number = d['avg_interest_rate_amt'] + '%'
            rows.append({'line': f'Average interest rate on outstanding {d["security_desc"]}, as of {latest}: {number}.',
                         'number': number, 'metric': 'average interest rate', 'period': latest})
    text = '\n\n'.join(r['line'] for r in rows)
    src = common.make_source(id='treasury-avg-rates-' + latest, source_id='primary_treasury', text=text,
                             publisher='U.S. Treasury (Fiscal Data)', title='Average interest rates on Treasury securities',
                             url=API, published_at=latest, adapter='treasury_fiscaldata')
    return src, common.data_units(src, rows, speaker='U.S. Treasury')


def fetch(*, transport=None):
    st, body = common.http_get(API, transport=transport)
    if st != 200:
        return {'status': f'http_{st}', 'sources': [], 'units': []}
    src, units = to_source_and_units(json.loads(body))
    return {'status': 'ok', 'sources': [src], 'units': units, 'requests': 1}
