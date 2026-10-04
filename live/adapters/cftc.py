"""CFTC Traders in Financial Futures, futures only (tier A)."""
from __future__ import annotations

import json
from urllib.parse import urlencode

from live.adapters import common

CODES = ('13874A', '043602', '099741', '133741', '209742')
API = 'https://publicreporting.cftc.gov/resource/gpe5-46if.json'
URL = API + '?' + urlencode({'$where': "cftc_contract_market_code in ('13874A','043602','099741','133741','209742') AND futonly_or_combined = 'FutOnly'",
                             '$order': 'report_date_as_yyyy_mm_dd DESC,cftc_contract_market_code', '$limit': 10})


def _net(row, prefix):
    return int(row[prefix + '_positions_long']) - int(row[prefix + '_positions_short'])


def to_source_and_units(data):
    data = [d for d in data if d['cftc_contract_market_code'] in CODES and d.get('futonly_or_combined', 'FutOnly') == 'FutOnly']
    dates = sorted({d['report_date_as_yyyy_mm_dd'][:10] for d in data}, reverse=True)[:2]
    rows = []
    if not dates:
        return common.structured_result(rows, id='cftc-empty', source_id='primary_cftc', publisher='CFTC',
                                        title='TFF futures only', url=URL, published_at='', adapter='cftc', tier='A')
    period = 'week ending ' + dates[0]
    by_key = {(d['cftc_contract_market_code'], d['report_date_as_yyyy_mm_dd'][:10]): d for d in data}
    for code in CODES:
        d = by_key.get((code, dates[0]))
        if not d:
            continue
        values = [('leveraged-funds net position', _net(d, 'lev_money')),
                  ('asset-manager net position', _net(d, 'asset_mgr'))]
        previous = by_key.get((code, dates[1])) if len(dates) > 1 else None
        if previous:
            values.append(('week-over-week change of leveraged-funds net position', _net(d, 'lev_money') - _net(previous, 'lev_money')))
        for metric, value in values:
            number = str(value)
            rows.append({'line': f'{d["contract_market_name"]} ({code}), {metric}, {period}: {number} contracts.',
                         'number': number, 'metric': metric, 'period': period})
    return common.structured_result(rows, id='cftc-tff-' + dates[0], source_id='primary_cftc', publisher='CFTC',
                                    title='TFF futures-only positioning', url=URL, published_at=dates[0], adapter='cftc', tier='A')


def fetch(*, transport=None):
    st, body = common.http_get(URL, transport=transport)
    if st != 200:
        return {'status': f'http_{st}', 'requests': 1, 'sources': [], 'units': []}
    return to_source_and_units(json.loads(body))
