"""live/media_real.py: per-account media profile, deterministic image decision, style gating, and fallback when a
capture or render fails (a draft is never blocked). No network, no browser: fetchers and captures are stubbed."""
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from live import charts, draft_media, media_real  # noqa: E402

CRYPTO_ACCT = {'id': 'crypto_trader_en', 'lang': 'en', 'kind': 'crypto', 'beat': 'Crypto trading · levels'}
STOCK_ACCT = {'id': 'zh_us_stocks', 'lang': 'zh', 'kind': 'stocks', 'beat': '美股个股'}
PROFILES = {'accounts': {
    'crypto_trader_en': {'image_rate': 0.4, 'chart_share': 0.5, 'p_image': 0.25, 'light_share': 0.5, 'tall_share': 0.1,
                         'styles': {'tv_drawn': 0.4, 'tv_widget': 0.2, 'mobile': 0.1, 'table': 0.1, 'panel': 0.2}},
    'zh_us_stocks': {'p_image': 0.1, 'light_share': 0.7, 'styles': {'tv_drawn': 0, 'tv_widget': 0, 'mobile': 1.0,
                                                                     'table': 0, 'panel': 0}}}}


def _bars(n=400, start=80000.0):
    rows, p = [], start
    for i in range(n):
        o = p
        c = p * (1 + 0.01 * math.sin(i / 5))
        rows.append([1_780_000_000 + i * 86400, o, max(o, c) * 1.005, min(o, c) * 0.995, c, 100 + i])
        p = c
    return rows


def _row(i, text, ptype='quick_take', **kw):
    return {'id': f'compose-{i}', 'day': '2026-10-08', 'text': text, 'post_format': {'type': ptype}, **kw}


def _fake_png(path, *_a, **_k):
    from PIL import Image
    im = Image.effect_noise((900, 500), 60).convert('RGB')
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


@pytest.fixture
def stub_data(monkeypatch, tmp_path):
    monkeypatch.setattr(charts, 'CACHE', tmp_path / 'cache')
    data = {'rows': _bars(), 'source': 'Binance spot', 'pair': 'BTCUSDT', 'interval': '1d', 'url': 'u',
            'fetched_at': '2026-10-08T00:00:00+00:00'}
    monkeypatch.setattr(charts, 'fetch_crypto', lambda *a, **k: dict(data))
    monkeypatch.setattr(charts, 'fetch_stock', lambda *a, **k: {**data, 'source': 'Yahoo Finance', 'pair': 'TSLA'})
    return data


# ------------------------------------------------------------------ profile + decision

def test_profile_for_known_and_default():
    p = media_real.profile_for('crypto_trader_en', PROFILES)
    assert p['p_image'] == 0.25 and p['source'] == 'profile' and p['styles']['tv_drawn'] == 0.4
    d = media_real.profile_for('nobody', PROFILES)
    assert d['source'] == 'default' and set(d['styles']) == set(media_real.STYLES)


def test_committed_profiles_cover_fd20_accounts():
    prof = json.loads((ROOT / 'live/media_profiles.json').read_text())
    ids = {a['id'] for a in json.loads((ROOT / 'live/fd20_accounts.json').read_text())['accounts']}
    assert ids <= set(prof['accounts'])
    for a in prof['accounts'].values():
        assert 0 < a['p_image'] < 0.6 and abs(sum(a['styles'].values()) - 1) < 0.02
    assert 'handle' not in json.dumps(prof).lower()   # aggregates only


def test_decision_is_deterministic_per_draft():
    row = _row(1, 'BTC rally into 85,000 resistance, chart looks heavy')
    a = media_real.decide(row, CRYPTO_ACCT, PROFILES)
    b = media_real.decide(dict(row), CRYPTO_ACCT, PROFILES)
    assert a == b


def test_image_rate_follows_profile():
    text = 'BTC price breaking out, support holds'
    wants = sum(media_real.decide(_row(i, text), CRYPTO_ACCT, PROFILES)['want'] for i in range(600))
    assert 0.19 < wants / 600 < 0.31   # p_image 0.25


def test_chart_caption_always_and_quote_never():
    text = 'BTC price breaking out'
    assert all(media_real.decide(_row(i, text, 'chart_caption'), CRYPTO_ACCT, PROFILES)['want'] for i in range(40))
    assert not any(media_real.decide(_row(i, text, 'quote_comment'), CRYPTO_ACCT, PROFILES, force=True)['want']
                   for i in range(40))
    assert not media_real.decide(_row(1, text, 'quick_take', post_mode='reply'), CRYPTO_ACCT, PROFILES, force=True)['want']


def test_off_topic_and_beat_gate():
    # ticker named in passing, no price talk -> no price chart
    d = media_real.decide(_row(1, 'Ethereum L2 teams are merging to survive the liquidity squeeze'), CRYPTO_ACCT,
                          PROFILES, force=True)
    assert not d['want'] and 'subject' in d['why']
    # crypto ticker on a stock account -> no crypto chart
    d = media_real.decide(_row(2, 'BTC 突破新高，比特币走势很强'), STOCK_ACCT, PROFILES, force=True)
    assert not d['want']


def test_named_levels_exclude_widget_and_table_needs_derivatives_talk():
    lv = media_real.decide(_row(3, 'BTC lost 84,000 support, needs to reclaim 85,500'), CRYPTO_ACCT, PROFILES, force=True)
    assert lv['want'] and 'tv_widget' not in lv['candidates'] and 'table' not in lv['candidates']
    fu = media_real.decide(_row(4, 'BTC funding flipped negative while price dumps'), CRYPTO_ACCT, PROFILES, force=True)
    assert 'table' in fu['candidates'] and 'tv_widget' in fu['candidates']


def test_style_weights_follow_profile():
    styles = [media_real.decide(_row(i, '$TSLA 股价跌破支撑，走势转弱'), STOCK_ACCT, PROFILES, force=True)['style']
              for i in range(60)]
    assert styles.count('mobile') >= 50   # mobile 1.0, others floored at 0.02


def test_series_draft_gets_panel():
    d = media_real.decide(_row(5, 'Real yields keep climbing; the 10y TIPS yield is the tell'), CRYPTO_ACCT, PROFILES,
                          force=True)
    assert d['want'] and d['style'] == 'panel' and d['series']['series'] == 'DFII10'


# ------------------------------------------------------------------ fallback: never block a draft

def test_widget_capture_failure_falls_back_to_rendered(tmp_path, monkeypatch, stub_data):
    row = _row(6, 'BTC price breaking out, chart is clean', 'chart_caption')
    monkeypatch.setattr(media_real, 'decide', lambda *a, **k: {
        'want': True, 'why': 'chart_caption', 'post_type': 'chart_caption', 'p_image': .2, 'profile_source': 'profile',
        'style': 'tv_widget', 'theme': 'dark', 'subject': {'asset': 'crypto', 'symbol': 'BTC', 'display': 'BTC'},
        'series': None, 'interval': '1d', 'candidates': ['tv_drawn', 'tv_widget'], 'seed': 3})
    monkeypatch.setattr(media_real, '_capture', lambda job, timeout=0: {'ok': False, 'error': 'TimeoutError'})
    monkeypatch.setattr(media_real, 'render_html', lambda cfg, out, **k: (_fake_png(out), {'ok': True})[1])
    media, plan = media_real.attach(row, CRYPTO_ACCT, tmp_path)
    assert media['style'] == 'tv_drawn' and media['capture'] is False
    assert plan['tried'][0]['style'] == 'tv_widget' and 'Timeout' in plan['tried'][0]['error']
    spec = json.loads((tmp_path / media['path']).with_suffix('.json').read_text())
    assert spec['tried'] and spec['version'] == 'media-v2'


def test_browser_down_falls_back_to_matplotlib(tmp_path, monkeypatch, stub_data):
    monkeypatch.setattr(media_real, '_capture', lambda job, timeout=0: {'ok': False, 'error': 'no browser'})
    monkeypatch.setattr(media_real, 'lwc_js', lambda: 'x')
    monkeypatch.setattr(charts, 'chart_profile', lambda a, h=None: {'candle': True, 'data': True, 'chart_share': .3, 'why': 't'})
    row = _row(7, 'BTC lost 84,000 support', 'chart_caption')
    media, plan = media_real.attach(row, CRYPTO_ACCT, tmp_path, profiles=PROFILES)
    assert media and media['style'] == 'matplotlib' and media['fallback_from']
    assert (tmp_path / media['path']).exists()


def test_everything_fails_no_image_and_text_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(charts, 'CACHE', tmp_path / 'cache')
    monkeypatch.setattr(charts, 'fetch_crypto', lambda *a, **k: {'rows': None, 'attempts': [{'error': '451'}]})
    monkeypatch.setattr(media_real, 'hyperliquid_ctx', lambda ttl=None: (None, {'error': '429'}))
    monkeypatch.setattr(media_real, 'okx_ctx', lambda ttl=None: (None, {'error': 'down'}))
    monkeypatch.setattr(media_real, '_capture', lambda job, timeout=0: {'ok': False, 'error': 'no browser'})
    monkeypatch.setattr(draft_media.post_mode, 'decide', lambda row, **k: {'post_mode': 'original'})
    row = _row(8, 'BTC funding flipped negative, price dumps', 'chart_caption', draft_status='draft_ready',
               account_id='crypto_trader_en')
    text = row['text']
    out = draft_media.annotate(row, CRYPTO_ACCT, tmp_path)
    assert out['text'] == text and 'media' not in out
    assert out['media_plan']['status'] == 'no_data' and out['media_plan']['detail']
    assert not list(tmp_path.glob('media/**/*.png'))


def test_builder_exception_is_caught(tmp_path, monkeypatch, stub_data):
    monkeypatch.setattr(media_real, 'BUILDERS', {k: (lambda *a, **k: 1 / 0) for k in media_real.BUILDERS})
    monkeypatch.setattr(media_real, '_capture', lambda job, timeout=0: {'ok': False, 'error': 'x'})
    monkeypatch.setattr(charts, 'attach_v1', lambda *a, **k: (None, None))
    media, plan = media_real.attach(_row(9, 'BTC price breaking out', 'chart_caption'), CRYPTO_ACCT, tmp_path,
                                    profiles=PROFILES)
    assert media is None and any('ZeroDivisionError' in t['error'] for t in plan['failed'])


def test_capture_subprocess_failure_is_a_result_not_an_exception(monkeypatch):
    monkeypatch.setenv('FD_CAPTURE_PYTHON', '/nonexistent/python')
    res = media_real._capture({'url': 'https://example.invalid', 'out': '/tmp/x.png'}, timeout=5)
    assert res['ok'] is False and res['error']


def test_blank_capture_rejected(tmp_path):
    from PIL import Image
    Image.new('RGB', (900, 500), 'white').save(tmp_path / 'b.png')
    _fake_png(tmp_path / 'n.png')
    assert not media_real._png_ok(tmp_path / 'b.png') and media_real._png_ok(tmp_path / 'n.png')


def test_no_image_by_rate_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(draft_media.post_mode, 'decide', lambda row, **k: {'post_mode': 'original'})
    monkeypatch.setattr(media_real, 'load_profiles', lambda path=None: {'accounts': {
        'crypto_trader_en': {**PROFILES['accounts']['crypto_trader_en'], 'p_image': 0.0}}})
    out = draft_media.annotate(_row(10, 'BTC price breaking out'), CRYPTO_ACCT, tmp_path)
    assert out['media_plan']['status'] == 'no_image' and 'donor rate' in out['media_plan']['why']


def test_rollback_flag_uses_v1(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(charts, 'attach_v1', lambda *a, **k: called.setdefault('v1', (None, None)))
    monkeypatch.setattr(media_real, 'attach', lambda *a, **k: called.setdefault('v2', (None, None)))
    monkeypatch.setenv('FD_MEDIA_V2', '0')
    charts.attach(_row(11, 'x'), CRYPTO_ACCT, tmp_path)
    monkeypatch.setenv('FD_MEDIA_V2', '1')
    charts.attach(_row(11, 'x'), CRYPTO_ACCT, tmp_path)
    assert set(called) == {'v1', 'v2'}


def test_levels_are_only_named_prices(stub_data):
    import random
    rows = stub_data['rows'][-120:]
    lo, hi = min(r[3] for r in rows), max(r[2] for r in rows)
    mid = round((lo + hi) / 2, -2)
    levels, zone, named = media_real._levels(f'BTC support {mid:,.0f}, 12% upside, 2026 target', rows,
                                             random.Random(1), 'en')
    drawn = [l['price'] for l in levels] + ([zone['bottom'], zone['top']] if zone else [])
    assert named == [mid] and drawn == [mid]


def test_profile_builder_tally_and_blend():
    import build_media_profiles as b
    recs = [({'category': 'tradingview_chart', 'annotations': ['boxes_zones'], 'theme': 'light'}, 1600, 900),
            ({'category': 'tradingview_chart', 'annotations': ['none'], 'theme': 'dark'}, 1600, 900),
            ({'category': 'exchange_app_screenshot', 'device': 'phone_screenshot', 'theme': 'dark'}, 1080, 2200),
            ({'category': 'meme_or_photo'}, 800, 800)]
    s = b.shares(b.tally(recs))
    assert s['chart_share'] == 0.75 and s['styles']['tv_drawn'] == pytest.approx(1 / 3)
    assert s['styles']['mobile'] == pytest.approx(1 / 3) and s['tall_share'] == pytest.approx(1 / 3)
    fam = {**s, 'chart_share': 0.5, 'n': 40}
    assert 0.5 < b.blend(s, fam)['chart_share'] < 0.75
