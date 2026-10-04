"""NY Fed SOFR rates, percentiles and volumes; deterministic tier A units."""
import json
from decimal import Decimal
from live.adapters import common
API = 'https://markets.newyorkfed.org/api/rates/secured/sofr/last/5.json'
PUBLISHER = 'Federal Reserve Bank of New York'


def to_source_and_units(data):
    rates = sorted((r for r in data.get('refRates', []) if r.get('type') == 'SOFR'),
                   key=lambda r: r['effectiveDate'], reverse=True)
    if not rates:
        return {'status': 'no_data', 'sources': [], 'units': [], 'requests': 1}
    latest = rates[0]; period = latest['effectiveDate']; rows = []
    for key, metric, suffix in [('percentRate', 'SOFR rate', 'percent'),
                                ('percentPercentile1', 'SOFR 1st percentile', 'percent'),
                                ('percentPercentile99', 'SOFR 99th percentile', 'percent'),
                                ('volumeInBillions', 'SOFR volume', '$bn')]:
        number = str(latest[key])
        rows.append({'line': f'{metric}, {period}: {number} {suffix}.', 'number': number + ' ' + suffix,
                     'metric': metric, 'period': period})
    if len(rates) >= 5:
        old = rates[4]; number = str(Decimal(str(latest['percentRate'])) - Decimal(str(old['percentRate'])))
        rows.append({'line': f'SOFR rate change versus {old["effectiveDate"]}, {period}: {number} percentage points.',
                     'number': number + ' percentage points', 'metric': 'SOFR rate change', 'period': period})
    return common.structured_result(rows, id='nyfed-sofr-'+period, source_id='primary_nyfed',
                    publisher=PUBLISHER, title='SOFR '+period, url=API, published_at=period, adapter='nyfed', tier='A')


def fetch(*, transport=None):
    st, body = common.http_get(API, transport=transport)
    if st != 200:
        return {'status': f'http_{st}', 'sources': [], 'units': [], 'requests': 1}
    return to_source_and_units(json.loads(body))
