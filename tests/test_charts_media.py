"""live/charts.py: subject / series / level parsing, account eligibility, and no chart without fetched data."""
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live import charts  # noqa: E402


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
    monkeypatch.setattr(charts, 'fetch_crypto', lambda sym, interval='1d', bars=150: {
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


def test_pick_interval_needs_a_chart_word():
    assert charts.pick_interval('4小时内就爆掉了4亿多单') == '1d'
    assert charts.pick_interval('4小时线收在均线下') == '4h'
    assert charts.pick_interval('weekly close above 90k') == '1w'
