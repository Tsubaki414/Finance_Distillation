"""Free daily options-positioning sources for trading_shortterm (deterministic units, no model calls)."""
import json
from datetime import date

from live import registry
from live.adapters import options_flow as of

DAILY = json.dumps({'ratios': [{'name': 'TOTAL PUT/CALL RATIO', 'value': '0.78'}, {'name': 'EQUITY PUT/CALL RATIO', 'value': '0.58'},
                               {'name': 'MXEA PUT/CALL RATIO', 'value': '0.00'}],
                    'SPX + SPXW': [{'name': 'VOLUME', 'call': 2564433, 'put': 2954897, 'total': 5519330}]})
VVIX = 'DATE,VVIX\n' + '\n'.join(f'09/{d:02d}/2026,{80 + d}.000000' for d in range(21, 31)) + '\n'
SKEW = 'DATE,SKEW\n10/02/2026,144.880000\n'
VIX1D = 'DATE,OPEN,HIGH,LOW,CLOSE\n10/02/2026,9.07,11.47,8.90,10.760000\n'
DIX = 'date,price,dix,gex\n' + ''.join(f'2026-{6 + i // 28:02d}-{1 + i % 28:02d},7000,0.45,{i}00000000\n' for i in range(70)) + \
      '2026-10-02,7722.72,0.4970775,7693512554.44\n'


def transport(url, headers):
    if 'daily_options' in url:
        return (200, DAILY) if '2026-10-02' in url else (403, 'no')
    for key, body in (('VVIX', VVIX), ('SKEW', SKEW), ('VIX1D', VIX1D)):
        if f'/{key}_History' in url:
            return 200, body
    if 'squeezemetrics' in url:
        return 200, DIX
    return 404, ''


def test_cboe_options_walks_back_to_latest_trading_day():
    out = of.fetch_cboe_options(transport=transport, today=date(2026, 10, 4))   # Sunday -> Fri 2 Oct
    lines = [u['statement'] for u in out['units']]
    assert out['status'] == 'ok' and out['requests'] == 1
    assert 'Cboe Total put/call ratio, 2026-10-02: 0.78.' in lines
    assert not any('MXEA' in l for l in lines)                                    # unlisted ratios ignored
    assert 'SPX + SPXW options volume, 2026-10-02: 5519330 contracts.' in lines


def test_vol_extra_and_squeezemetrics_units_are_traceable():
    out = of.fetch(transport=transport)
    assert out['parts'] == ['ok', 'ok', 'ok'] and len(out['sources']) == 3
    lines = [u['statement'] for u in out['units']]
    assert 'Cboe SKEW index latest close, 2026-10-02: 144.88.' in lines
    assert any(l.startswith('VVIX 5-trading-day change, 2026-09-30: 5.00') for l in lines)
    assert 'SqueezeMetrics DIX (dark-pool short-volume index), 2026-10-02: 49.7%.' in lines
    assert any(l.startswith('SqueezeMetrics GEX (estimated dealer gamma exposure), 2026-10-02: $7.69 billion') for l in lines)
    assert any('percentile' in l and ('st ' in l or 'nd ' in l or 'rd ' in l or 'th ' in l) for l in lines)
    for u in out['units']:
        assert u['source_spans'][0]['exact_text'] == u['statement']


def test_new_sources_have_writable_licence_and_display_names():
    disp = json.load(open(registry.ROOT / 'source_display.json'))['sources']
    for sid in ('cboe_options_stats', 'squeezemetrics_dix', 'ch140_moontowermeta_com'):
        assert registry.source_licence_tier(sid) == 'B'
        assert disp[sid]['en']
