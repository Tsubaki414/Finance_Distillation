"""DefiLlama stablecoin pool yields (Oct 8, 36 accounts: stablecoin-yield lane). Tier B, structured, no model call.

One read-only GET to the free yields API (no key): stablecoin pools only. Lines: the TVL-weighted APY of the
largest stablecoin pools, then the largest pools one by one (project, chain, symbol, APY, TVL, 30-day mean APY).
Aggregates and project names only; never an address.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from live.adapters import common

API = 'https://yields.llama.fi/pools'
SOURCE_ID = 'defillama_yields'
MIN_TVL = 100e6


def _bn(x):
    return f'${x / 1e9:.2f}bn' if x >= 1e9 else f'${x / 1e6:.0f}m'


def fetch(*, top=8, transport=None, now=None):
    st, body = common.http_get(API, transport=transport, timeout=60)
    if st != 200:
        return {'status': f'http_{st}', 'requests': 1, 'sources': [], 'units': []}
    now = now or datetime.now(timezone.utc)
    period = now.date().isoformat()
    pools = [p for p in json.loads(body).get('data') or []
             if p.get('stablecoin') and p.get('exposure') == 'single' and (p.get('tvlUsd') or 0) >= MIN_TVL
             and p.get('apy') is not None]
    pools.sort(key=lambda p: -p['tvlUsd'])
    rows = []
    if pools:
        big = pools[:25]
        tvl = sum(p['tvlUsd'] for p in big)
        avg = f"{sum(p['apy'] * p['tvlUsd'] for p in big) / tvl:.2f}%"
        rows.append({'line': f'TVL-weighted APY of the {len(big)} largest single-asset stablecoin pools on DefiLlama, '
                             f'{period}: {avg} (pools above $100m TVL).',
                     'number': avg, 'metric': 'stablecoin pool TVL-weighted APY', 'period': period})
    for p in pools[:top]:
        apy = f"{p['apy']:.2f}%"
        nums = [{'text': apy, 'metric': f"{p['project']} {p['symbol']} APY", 'period': period, 'span_ref': 0},
                {'text': _bn(p['tvlUsd']), 'metric': f"{p['project']} {p['symbol']} TVL", 'period': period, 'span_ref': 0}]
        mean = f"{p['apyMean30d']:.2f}%" if p.get('apyMean30d') is not None else None
        line = f"DefiLlama stablecoin pool {p['project']} {p['symbol']} on {p['chain']}, {period}: APY {apy}, TVL {_bn(p['tvlUsd'])}"
        if mean and mean != apy:
            line += f', 30-day mean APY {mean}'
            nums.append({'text': mean, 'metric': f"{p['project']} {p['symbol']} 30-day mean APY", 'period': period,
                         'span_ref': 0})
        rows.append({'line': line + '.', 'metric': nums[0]['metric'], 'period': period, 'number': apy, 'numbers': nums})
    return common.structured_result(rows, id=f'{SOURCE_ID}-{period}', source_id=SOURCE_ID, publisher='DefiLlama',
                                    title='Stablecoin pool yields (largest pools)', url=f'{API}#{period}', published_at=period,
                                    adapter='defillama_yields')
