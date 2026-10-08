"""live/charts.py: subject / series / level parsing, account eligibility, and no chart without fetched data."""
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live import charts  # noqa: E402


@pytest.fixture(autouse=True)
def _v1_path(monkeypatch):
    """These tests pin the Oct 7 matplotlib path (FD_MEDIA_V2=0); tests/test_media_real.py covers the default."""
    monkeypatch.setenv('FD_MEDIA_V2', '0')


def _bars(n=120, start=80000.0):
    rows, p = [], start
    for i in range(n):
        o = p
        c = p * (1 + 0.01 * math.sin(i / 5))
        rows.append([1_780_000_000 + i * 86400, o, max(o, c) * 1.005, min(o, c) * 0.995, c, 100 + i])
        p = c
    return rows


def test_pick_subject_crypto_stock_and_noise():
    assert charts.pick_subject('大饼回到 8.5万，BTC 周线还稳，ETH 一般')['symbol'] == 'BTC'
    s = charts.pick_subject('$NVDA into earnings; Nvidia holds 180')
    assert (s['asset'], s['symbol']) == ('stock', 'NVDA')
    assert charts.pick_subject('标普又新高了')['symbol'] == '^GSPC'
    assert charts.pick_subject('The AI trade, US ETF flows and the CEO letter') is None
    assert charts.pick_subject('') is None


def test_pick_series():
    assert charts.pick_series('10Y yield back above 4.3%')['series'] == 'DGS10'
    assert charts.pick_series('稳定币总量又创新高')['series'] == 'stablecoins'
    assert charts.pick_series('Solana TVL keeps climbing')['series'] == 'tvl:Solana'
    assert charts.pick_series('nothing to plot here') is None


def test_draft_levels_only_inside_fetched_range():
    text = '支撑 85000，压力 90,000 和 $95k；2026 年目标 200k；涨了 12%；成交 30 亿'
    assert charts.draft_levels(text, 80000, 88000) == [85000.0, 90000.0, 95000.0]
    assert charts.draft_levels('ETH 2026 cycle, support 2400', 2200, 2700) == [2400.0]   # a year is not a level
    assert charts.draft_levels('target 1,000,000', 80000, 88000) == []


def test_chart_profile(tmp_path):
    (tmp_path / 'acct_t.json').write_text(json.dumps({'post_type_mix': {'chart_caption': 0.4}}))
    (tmp_path / 'acct_n.json').write_text(json.dumps({'post_type_mix': {'chart_caption': 0.05}}))
    trader = charts.chart_profile({'id': 'acct_n', 'kind': 'crypto', 'beat': '交易员复盘 · K线点位与仓位'}, tmp_path)
    assert trader['candle'] and not trader['data']
    heavy = charts.chart_profile({'id': 'acct_t', 'kind': 'crypto', 'beat': '散户视角'}, tmp_path)
    assert heavy['candle']
    macro = charts.chart_profile({'id': 'acct_n', 'kind': 'crypto', 'beat': 'Crypto macro'}, tmp_path)
    assert macro['data'] and not macro['candle']
    plain = charts.chart_profile({'id': 'acct_n', 'kind': 'stocks', 'beat': 'Single-stock deep dives'}, tmp_path)
    assert not plain['candle'] and not plain['data']


def test_no_chart_without_fetched_data(tmp_path, monkeypatch):
    monkeypatch.setattr(charts, 'chart_profile', lambda a, h=None: {'candle': True, 'data': True, 'chart_share': 0.3, 'why': 't'})
    monkeypatch.setattr(charts, 'fetch_crypto', lambda *a, **k: {'rows': None, 'attempts': [{'error': '451'}]})
    row = {'id': 'd1', 'day': '2026-10-07', 'text': 'BTC 85000 支撑'}
    media, plan = charts.attach(row, {'id': 'x'}, tmp_path)
    assert media is None and plan['failed']
    assert not list(tmp_path.rglob('*.png'))


def test_attach_renders_from_fetched_rows(tmp_path, monkeypatch):
    pytest.importorskip('matplotlib')
    monkeypatch.setattr(charts, 'chart_profile', lambda a, h=None: {'candle': True, 'data': False, 'chart_share': 0.3, 'why': 't'})
    monkeypatch.setattr(charts, 'fetch_crypto', lambda sym, interval='1d', bars=150, ttl=None: {
        'rows': _bars(), 'source': 'Binance spot', 'pair': f'{sym}USDT', 'interval': interval,
        'url': 'https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT', 'fetched_at': '2026-10-07T10:00:00+00:00'})
    row = {'id': 'd2', 'day': '2026-10-07', 'text': 'BTC 守住 80000，上方看 1,000,000'}
    media, plan = charts.attach(row, {'id': 'x'}, tmp_path)
    assert plan['kind'] == 'candle' and media['path'] == 'media/2026-10-07/d2.png'
    png = tmp_path / media['path']
    assert png.read_bytes()[:4] == b'\x89PNG'
    spec = json.loads(png.with_suffix('.json').read_text())
    assert spec['data_source'] == 'Binance spot' and spec['url'].startswith('https://')
    assert 1_000_000.0 not in media['levels']      # outside the fetched range: never drawn
    assert media['refreshed_at'] and media['data_sha'] and spec['refreshed_at'] == media['refreshed_at']


def test_pick_interval_needs_a_chart_word():
    assert charts.pick_interval('4小时内就爆掉了4亿多单') == '1d'
    assert charts.pick_interval('4小时线收在均线下') == '4h'
    assert charts.pick_interval('weekly close above 90k') == '1w'


def test_draft_levels_skip_numbers_that_are_not_prices():
    lv = charts.draft_levels
    assert lv('$487.2 million in long positions were wiped out', 300, 600) == []
    assert lv('4小时内就爆掉了4.153亿美元多单', 3, 600) == []
    assert lv('holds 500 BTC, 600 days, 650 wallets, up 550%', 400, 700) == []
    assert lv('剩下最后 30 天，份额从 60% 下调到 55%', 20, 70) == []
    assert lv('10/7 18:30 更新', 1, 40) == []
    assert lv('BTC 跌破 8.5万 之后，下一个支撑在 8万美元，上方压力 9.2万', 70000, 90000) == [85000.0, 80000.0, 92000.0]
    assert lv('Bitcoin needs to reclaim 112k; below 105,000 opens 98k', 95000, 115000) == [112000.0, 105000.0, 98000.0]
    assert lv('NVDA $180 is the line, 175-185 range, P/E 45x', 150, 200) == [180.0, 175.0, 185.0]
    assert lv('support 2400', 2200, 2700, last=5000) == []       # far from the current price: not drawn


def test_refresh_replaces_only_changed_charts(tmp_path, monkeypatch):
    pytest.importorskip('matplotlib')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import refresh_charts
    from datetime import datetime, timezone
    monkeypatch.setattr(charts, 'chart_profile', lambda a, h=None: {'candle': True, 'data': False, 'chart_share': 0.3, 'why': 't'})
    bars = {'rows': _bars()}
    calls = []

    def fake(sym, interval='1d', bars_n=150, ttl=None):
        calls.append(ttl)
        return {'rows': bars['rows'], 'source': 'Binance spot', 'pair': f'{sym}USDT', 'interval': interval,
                'url': 'https://x', 'fetched_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    monkeypatch.setattr(charts, 'fetch_crypto', fake)
    inbox, out = tmp_path / 'inbox', tmp_path / 'out'
    (inbox / '2026-10-07').mkdir(parents=True)
    row = {'id': 'd3', 'day': '2026-10-07', 'account_id': 'a', 'draft_status': 'draft_ready',
           'text': 'BTC 守住 $84,000 支撑'}
    media, _ = charts.attach(row, {'id': 'a'}, out)
    row['media'] = [media]
    f = inbox / '2026-10-07' / 'd3.json'
    f.write_text(json.dumps(row))
    accounts = {'a': {'id': 'a'}}
    s = refresh_charts.refresh_days(['2026-10-07', '2026-10-08'], out, inbox, accounts)
    assert (s['same'], s['changed']) == (1, 0) and calls[-1] == 0          # refetched, same data: image kept
    bars['rows'] = _bars(start=81000.0)
    s = refresh_charts.refresh_days(['2026-10-07'], out, inbox, accounts)
    assert s['changed'] == 1
    new = json.loads(f.read_text())
    assert new['text'] == row['text'] and new['media'][0]['sha256'] != media['sha256']
    assert new['media'][0]['refreshed_at'] and new['media'][0]['levels'] == [84000.0]
    assert json.loads((out / media['path']).with_suffix('.json').read_text())['sha256'] == new['media'][0]['sha256']
