"""FRED (St. Louis Fed). Needs FRED_API_KEY (not on the box: flagged). Only
public-domain series (BLS/BEA/Fed/Treasury) are tier A; third-party series
(ICE BofA, S&P, Moody's ...) carry their owner's copyright and are not used."""
from __future__ import annotations

import json
import os

from live.adapters import common

API = 'https://api.stlouisfed.org/fred/series/observations'
PUBLIC_DOMAIN = {'UNRATE', 'PAYEMS', 'CPIAUCSL', 'PCEPI', 'DFF', 'DGS10', 'DGS2', 'T10Y2Y', 'WALCL', 'M2SL', 'GDP'}


def fetch_series(series_id, *, limit=2, transport=None):
    key = os.environ.get('FRED_API_KEY', '').strip()
    if not key:
        return {'status': 'missing_api_key', 'series': series_id, 'sources': [], 'units': []}
    if series_id not in PUBLIC_DOMAIN:
        return {'status': 'series_not_cleared', 'series': series_id, 'sources': [], 'units': []}
    st, body = common.http_get(f'{API}?series_id={series_id}&api_key={key}&file_type=json&sort_order=desc&limit={limit}',
                               transport=transport)
    if st != 200:
        return {'status': f'http_{st}', 'series': series_id, 'sources': [], 'units': []}
    obs = json.loads(body)['observations']
    rows = [{'line': f'{series_id} (FRED), {o["date"]}: {o["value"]}.', 'number': o['value'], 'metric': series_id,
             'period': o['date']} for o in obs[:1]]
    text = '\n\n'.join(r['line'] for r in rows)
    src = common.make_source(id=f'fred-{series_id}-{obs[0]["date"]}', source_id='primary_fed', text=text,
                             publisher='Federal Reserve Bank of St. Louis (FRED)', title=series_id,
                             url=f'https://fred.stlouisfed.org/series/{series_id}', published_at=obs[0]['date'],
                             adapter='fred_api')
    return {'status': 'ok', 'series': series_id, 'sources': [src], 'units': common.data_units(src, rows, speaker='FRED')}
