"""live/media_sources.py + its wiring in live/media_real.py (media v3): which donor source fits a draft, the
FD_MEDIA_SOURCES rollback, manual-only sources, page checks, and the fallback chain when a source capture fails.
No network, no browser: captures and fetchers are stubbed."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live import charts, media_real, media_sources  # noqa: E402

CRYPTO = {'id': 'crypto_trader_en', 'lang': 'en', 'kind': 'crypto'}
STOCKS = {'id': 'zh_us_stocks', 'lang': 'zh', 'kind': 'stocks'}
V3 = {'p_image': 0.3, 'light_share': 0.5, 'tall_share': 0.1,
      'styles': {'tv_drawn': 0.3, 'tv_widget': 0.1, 'mobile': 0.1, 'table': 0.05, 'panel': 0.3, 'x_post': 0.05,
                 'article': 0.05, 'etf_flows': 0.02, 'polymarket': 0.02}}
V2 = {'p_image': 0.0, 'light_share': 0.5, 'styles': {'tv_drawn': 0.4, 'tv_widget': 0.1, 'mobile': 0.1, 'table': 0.1,
                                                      'panel': 0.3}}
PROFILES = {'accounts': {'crypto_trader_en': {**V3, 'v2': V2}, 'zh_us_stocks': {**V3, 'v2': V2}}}
XURL = 'https://x.com/example_trader/status/1900000000000000001'


def _row(i, text, url=None, **kw):
    return {'id': f'compose-{i}', 'day': '2026-10-08', 'text': text, 'post_format': {'type': 'judgment_take'},
            'source': {'url': url} if url else {}, **kw}


def _fake_png(path):
    from PIL import Image
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.effect_noise((900, 500), 60).convert('RGB').save(path)


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.delenv('FD_MEDIA_SOURCES', raising=False)
    monkeypatch.delenv('FD_MEDIA_CAPTURE', raising=False)
    monkeypatch.setattr(charts, 'CACHE', tmp_path / 'cache')
    monkeypatch.setattr(media_sources, 'HOST_GAP_S', 0)


# ------------------------------------------------------------------ which source fits

def test_x_source_from_draft_source_url():
    assert media_sources.x_source(_row(1, 't', XURL)) == ('example_trader', '1900000000000000001')
    assert media_sources.x_source(_row(1, 't', 'https://www.coindesk.com/markets/x')) is None


def test_candidates_x_post_not_for_quote_posts():
    assert 'x_post' in media_sources.candidates(_row(1, 'bullish', XURL), CRYPTO, 'bullish')
    assert 'x_post' not in media_sources.candidates(_row(1, 'bullish', XURL, post_mode='quote'), CRYPTO, 'bullish')


@pytest.mark.parametrize('text,asset', [
    ('Zcash ETF just vacuumed up $1 billion in its initial month', 'ZEC'),
    ('比特币现货ETF昨天净流出4.8亿美元', 'BTC'),
    ('以太坊 ETF 连续三天资金流入', 'ETH'),
    ('ETF approvals are coming', None),            # ETF without flow talk
    ('inflows into gold are surging', None),       # flow talk without ETF
])
def test_etf_asset(text, asset):
    assert media_sources.etf_asset(text) == asset


def test_etf_flows_only_on_crypto_accounts():
    text = 'Bitcoin ETF inflows hit $500M yesterday'
    assert 'etf_flows' in media_sources.candidates(_row(1, text), CRYPTO, text)
    assert 'etf_flows' not in media_sources.candidates(_row(1, text), STOCKS, text)


def test_polymarket_topic_and_explicit_odds():
    assert media_sources.pm_topic('期权市场对这次中期选举的定价太乐观')[0] == 'midterms'
    q, _t, explicit = media_sources.pm_topic('Polymarket odds of a Fed rate cut in October are collapsing')
    assert q == 'fed decision' and explicit
    assert media_sources.pm_topic('NVDA earnings beat') is None


def test_article_only_for_allow_listed_sites():
    assert media_sources.article_source(_row(1, 't', 'https://www.theblockbeats.info/flash/370791'))['site'] == 'BlockBeats'
    assert media_sources.article_source(_row(1, 't', 'https://www.coindesk.com/markets/2026/10/07/x')) is None


def test_flag_off_means_no_candidates(monkeypatch):
    monkeypatch.setenv('FD_MEDIA_SOURCES', '0')
    text = 'Bitcoin ETF inflows hit $500M; Polymarket odds of a Fed cut'
    assert media_sources.candidates(_row(1, text, XURL), CRYPTO, text) == {}


def test_manual_sources_named_never_loaded():
    text = 'Liquidations above $92K are stacking up'
    m = media_sources.manual_sources(_row(1, text, 'https://www.coindesk.com/markets/2026/10/07/x'), text)
    names = [x['source'] for x in m]
    assert 'CoinDesk article' in names and 'CoinGlass liquidation heatmap' in names
    stock = media_sources.manual_sources(_row(1, 'TSLA'), 'TSLA', {'asset': 'stock', 'display': 'TSLA'})
    assert stock[0]['url'].endswith('s=TSLA') and 'Chart courtesy of StockCharts.com' in stock[0]['why']


# ------------------------------------------------------------------ decide()

def test_x_sourced_draft_without_chart_subject_gets_its_post(monkeypatch):
    row = _row(7, 'Insanely bullish on this options protocol, still cheap relative to its market', XURL)
    plan = media_real.decide(row, CRYPTO, PROFILES, force=True)
    assert plan['want'] and plan['style'] == 'x_post' and plan['sources']['x_post']['handle'] == 'example_trader'
    assert plan['fallback_style'] is None   # nothing else to draw: a failed capture means no image
    monkeypatch.setenv('FD_MEDIA_SOURCES', '0')
    assert media_real.decide(row, CRYPTO, PROFILES, force=True)['want'] is False   # v2: no chartable subject


def test_flag_off_uses_v2_profile_numbers(monkeypatch):
    monkeypatch.setenv('FD_MEDIA_SOURCES', '0')
    p = media_real.profile_for('crypto_trader_en', PROFILES)
    assert p['p_image'] == 0.0 and 'x_post' not in p['styles']
    monkeypatch.setenv('FD_MEDIA_SOURCES', '1')
    assert media_real.profile_for('crypto_trader_en', PROFILES)['p_image'] == 0.3


def test_drafts_without_a_source_keep_their_v2_draw(monkeypatch):
    """Same profile, no source candidate: v3 decides exactly like v2 (same style, theme and seed)."""
    prof = {'accounts': {'crypto_trader_en': V2 | {'p_image': 0.3}}}
    row = _row(11, 'BTC price broke above resistance, next level 90,000 support 82,000')
    a = media_real.decide(row, CRYPTO, prof, force=True)
    monkeypatch.setenv('FD_MEDIA_SOURCES', '0')
    b = media_real.decide(row, CRYPTO, prof, force=True)
    assert {k: a[k] for k in ('style', 'theme', 'seed', 'candidates')} == {k: b[k] for k in ('style', 'theme', 'seed', 'candidates')}


def test_topic_source_wins_over_profile_weight():
    text = 'BTC price: spot Bitcoin ETF inflows topped $900M yesterday, the biggest day since July'
    hits = sum(media_real.decide(_row(i, text), CRYPTO, PROFILES, force=True)['style'] == 'etf_flows' for i in range(60))
    assert 35 <= hits <= 55   # SOURCE_SHARE 0.75: chosen most of the time, never forced


def test_crypto_etf_never_on_stock_accounts():
    text = '比特币 ETF 净流入创新高，美股券商股跟涨'
    for i in range(20):
        assert media_real.decide(_row(i, text), STOCKS, PROFILES, force=True).get('style') != 'etf_flows'


# ------------------------------------------------------------------ capture checks + fallback chain

def test_capture_page_rejects_walls_and_caches(tmp_path):
    calls = []

    def cap(job):
        calls.append(job)
        _fake_png(job['out'])
        return {'ok': True, 'info': {'text': job['url'].endswith('wall') and '403 Access denied' or 'Bitcoin ETF Flow ' * 5}}
    ok, info = media_sources.capture_page({'url': 'https://e.x/wall'}, tmp_path / 'a.png', 'k1', 3600, cap)
    assert not ok and 'wall' in info['error']
    ok, info = media_sources.capture_page({'url': 'https://e.x/ok'}, tmp_path / 'b.png', 'k2', 3600, cap)
    assert ok and (tmp_path / 'b.png').exists() and info['text_sha']
    assert any('cookie' in h for h in calls[-1]['hide'])   # consent banners hidden, never clicked
    ok, info = media_sources.capture_page({'url': 'https://e.x/ok'}, tmp_path / 'c.png', 'k2', 3600, cap)
    assert ok and info['cached'] and len(calls) == 2   # second draft: no second page load


def test_failed_source_capture_falls_back_to_v2_style(monkeypatch, tmp_path):
    rows = [[1_780_000_000 + i * 86400, 100 + i, 102 + i, 99 + i, 101 + i, 10] for i in range(400)]
    monkeypatch.setattr(charts, 'fetch_crypto', lambda *a, **k: {'rows': rows, 'source': 'Binance spot', 'url': 'u',
                                                                  'fetched_at': 'now'})
    monkeypatch.setattr(media_sources, 'CAPTURERS', {**media_sources.CAPTURERS,
                                                     'x_post': lambda *a, **k: (False, {'error': 'wall / empty page'})})
    monkeypatch.setattr(media_real, 'render_html', lambda cfg, out, **k: (_fake_png(out), {'ok': True})[1])
    row = _row(3, 'BTC price looks heavy here, next support 82,000', XURL)
    for i in range(40):   # find a draft id whose draw is x_post with a v2 fallback
        row['id'] = f'compose-fb{i}'
        plan = media_real.decide(row, CRYPTO, PROFILES, force=True)
        if plan['style'] == 'x_post' and plan['fallback_style'] not in (None, 'tv_widget'):
            break
    else:
        pytest.skip('no x_post draw in 40 ids')
    media, plan = media_real.attach(row, CRYPTO, tmp_path, profiles=PROFILES, force=True)
    assert media and media['style'] == plan['fallback_style'] and plan['tried'][0]['style'] == 'x_post'
    assert row['text'] == 'BTC price looks heavy here, next support 82,000'


def test_source_capture_success_is_a_data_image(monkeypatch, tmp_path):
    def fake_x(detail, theme, lang, out, capture):
        _fake_png(out)
        return True, {'page': XURL, 'source_name': 'X post @example_trader (official embed)',
                      'captured_at': '2026-10-08T10:00:00+00:00', 'text_sha': 'abc'}
    monkeypatch.setattr(media_sources, 'CAPTURERS', {**media_sources.CAPTURERS, 'x_post': fake_x})
    row = _row(7, 'Insanely bullish on this options protocol, still cheap relative to its market', XURL)
    media, plan = media_real.attach(row, CRYPTO, tmp_path, profiles=PROFILES, force=True)
    assert media['style'] == 'x_post' and media['chart_type'] == 'data' and media['credit'] == '@example_trader on X'
    assert media['data_sources'][0]['url'] == XURL
    spec = json.loads((tmp_path / media['path']).with_suffix('.json').read_text())
    assert spec['version'] == 'media-v3' and spec['decision']['sources']['x_post']['status_id']


def test_no_fallback_and_failed_capture_means_no_image(monkeypatch, tmp_path):
    monkeypatch.setattr(media_sources, 'CAPTURERS', {**media_sources.CAPTURERS,
                                                     'x_post': lambda *a, **k: (False, {'error': 'timeout'})})
    monkeypatch.setattr(media_real, '_old_attach', lambda *a, **k: (None, {}))
    row = _row(7, 'Insanely bullish on this options protocol, still cheap relative to its market', XURL)
    media, plan = media_real.attach(row, CRYPTO, tmp_path, profiles=PROFILES, force=True)
    assert media is None and plan['failed'][0]['style'] == 'x_post'


def test_captures_disabled_skips_source_pages(monkeypatch, tmp_path):
    monkeypatch.setenv('FD_MEDIA_CAPTURE', '0')
    monkeypatch.setattr(media_real, '_old_attach', lambda *a, **k: (None, {}))
    called = []
    monkeypatch.setattr(media_sources, 'CAPTURERS', {**media_sources.CAPTURERS, 'x_post': lambda *a, **k: called.append(1)})
    row = _row(7, 'Insanely bullish on this options protocol, still cheap relative to its market', XURL)
    media, plan = media_real.attach(row, CRYPTO, tmp_path, profiles=PROFILES, force=True)
    assert media is None and not called and plan['failed'][0]['error'] == 'captures disabled'


def test_polymarket_market_picks_top_event_and_leading_outcome(monkeypatch):
    class R:
        def json(self):
            mk = lambda slug, p: {'slug': slug, 'question': slug, 'active': True, 'closed': False,   # noqa: E731
                                  'outcomePrices': json.dumps([str(p), str(1 - p)])}
            return {'events': [
                {'slug': 'small', 'title': 'Which party will win the Senate in 2026?', 'volume': 5, 'active': True,
                 'closed': False, 'markets': [mk('s-d', 0.6)]},
                {'slug': 'house', 'title': 'Which party will win the House in 2026?', 'volume': 9, 'active': True,
                 'closed': False, 'markets': [mk('h-d', 0.91), mk('h-r', 0.09)]},
                {'slug': 'other', 'title': 'Elon tweets', 'volume': 99, 'active': True, 'closed': False,
                 'markets': [mk('e', 0.5)]}]}
    monkeypatch.setattr(charts, '_get', lambda url, prov, series, key, parse, **kw: (parse(R()), {}))
    mk, _ = media_sources.polymarket_market('midterms')
    assert mk['event_slug'] == 'house' and mk['market_slug'] == 'h-d'
