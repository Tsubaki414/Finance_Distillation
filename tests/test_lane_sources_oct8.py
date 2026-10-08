"""Oct 8 evening (PM_PLAN item 4 / pm_sources): structured lane material + lane flashes for the 10 niche accounts.
Fixtures only, no network."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from live import lane_fit, lane_sources, registry, source_routes
from live.adapters import lane_data, lane_flashes

NOW = datetime(2026, 10, 8, 22, 13, tzinfo=timezone.utc)   # 23:13 London = 06:13 Beijing 10-09


def fake(by_url):
    """transport: first key that is a substring of the URL wins."""
    def t(url, headers):
        for k, body in by_url.items():
            if k in url:
                return 200, json.dumps(body)
        return 404, ''
    return t


YIELDS = {'data': [
    {'chain': 'Ethereum', 'project': 'morpho-blue', 'symbol': 'USDC', 'tvlUsd': 4e8, 'apy': 5.4, 'apyPct7D': -4.5,
     'stablecoin': True, 'exposure': 'single'},
    {'chain': 'Solana', 'project': 'jupiter-lend', 'symbol': 'PYUSD', 'tvlUsd': 2.4e8, 'apy': 3.55, 'apyPct7D': 1.9,
     'stablecoin': True, 'exposure': 'single'},
    {'chain': 'Ethereum', 'project': 'newpool', 'symbol': 'USAT', 'tvlUsd': 3e8, 'apy': 6.2, 'apyPct7D': 6.2,
     'stablecoin': True, 'exposure': 'single'},
    {'chain': 'Arbitrum', 'project': 'pendle-v2', 'symbol': 'USDAI', 'tvlUsd': 5e7, 'apy': 11.37, 'apyPct7D': 0.1,
     'poolMeta': 'For buying PT-USDai-15OCT2026', 'stablecoin': True, 'exposure': 'single'},
    {'chain': 'Arbitrum', 'project': 'pendle-v2', 'symbol': 'USDAI', 'tvlUsd': 5e7, 'apy': 3.0, 'apyPct7D': 0.1,
     'poolMeta': 'For LP | Maturity 15OCT2026', 'stablecoin': True, 'exposure': 'single'},
    {'chain': 'Ethereum', 'project': 'ethena-usde', 'symbol': 'SUSDE', 'tvlUsd': 1.2e9, 'apy': 5.02,
     'stablecoin': True, 'exposure': 'single'},
    {'chain': 'Ethereum', 'project': 'ondo-yield-assets', 'symbol': 'USDY', 'tvlUsd': 1.2e9, 'apy': 3.64,
     'stablecoin': True, 'exposure': 'single'},
    {'chain': 'Ethereum', 'project': 'lido', 'symbol': 'STETH', 'tvlUsd': 2e10, 'apy': 3, 'apyPct7D': 9,
     'stablecoin': False, 'exposure': 'single'}]}
OI = {'protocols': [
    {'name': 'Hyperliquid Perps', 'displayName': 'Hyperliquid Perps', 'category': 'Derivatives', 'total24h': 8.33e9,
     'change_1d': -4.34, 'change_7d': 1.46, 'defillamaId': '1'},
    {'name': 'Variational', 'category': 'Derivatives', 'total24h': 1.08e9, 'change_1d': -6.0, 'change_7d': 5.5,
     'defillamaId': '2'},
    {'name': 'Kalshi', 'category': 'Prediction Market', 'total24h': 1.42e9, 'change_1d': 18.4, 'change_7d': 12.8,
     'defillamaId': '3'},
    {'name': 'Polymarket International', 'category': 'Prediction Market', 'total24h': 3.4e8, 'change_1d': 1.4,
     'change_7d': -0.5, 'defillamaId': '4'}]}
PROTOCOLS = [
    {'id': '2', 'name': 'Variational', 'category': 'Derivatives', 'gecko_id': None, 'symbol': '-', 'tvl': 9e7,
     'change_7d': 5, 'chains': ['Arbitrum'], 'chainTvls': {'Arbitrum': 9e7}},
    {'id': '3', 'name': 'Kalshi', 'category': 'Prediction Market', 'gecko_id': None, 'symbol': '-', 'tvl': 0,
     'chains': ['Off Chain'], 'chainTvls': {}},
    {'id': '5', 'name': 'Symbiotic', 'category': 'Collateral Markets', 'gecko_id': None, 'symbol': '-', 'tvl': 4.6e8,
     'change_7d': -2.9, 'chains': ['Ethereum'], 'chainTvls': {'Ethereum': 4.6e8}},
    {'id': '6', 'name': 'Binance staked ETH', 'category': 'Lending', 'gecko_id': None, 'symbol': '-', 'tvl': 9e9,
     'change_7d': -5, 'chains': ['Ethereum'], 'chainTvls': {'Ethereum': 9e9}},
    {'id': '7', 'name': 'Kamino', 'category': 'Lending', 'gecko_id': 'kamino', 'symbol': 'KMNO', 'tvl': 2e9,
     'change_7d': 12.0, 'chains': ['Solana'], 'chainTvls': {'Solana': 2e9}},
    {'id': '8', 'name': 'Aerodrome', 'category': 'Dexs', 'gecko_id': 'aerodrome', 'symbol': 'AERO', 'tvl': 5e8,
     'change_7d': -8.0, 'chains': ['Base'], 'chainTvls': {'Base': 5e8}}]
FEES = {'protocols': [
    {'name': 'pump.fun', 'category': 'Launchpad', 'total24h': 2.4e6, 'change_1d': -5.3, 'change_7d': 11.1, 'chains': ['Solana']},
    {'name': 'LetsBonk', 'category': 'Launchpad', 'total24h': 2.0e5, 'change_1d': 3.0, 'change_7d': -20, 'chains': ['Solana']},
    {'name': 'Uniswap', 'category': 'Dexs', 'total24h': 3e6, 'change_1d': 1, 'chains': ['Ethereum']}]}
HL = [{'universe': [{'name': 'BTC'}, {'name': 'kPEPE'}, {'name': 'VVV'}, {'name': 'OLD', 'isDelisted': True}]},
      [{'funding': '0.0000125', 'openInterest': '40000', 'markPx': '83000', 'prevDayPx': '84000', 'dayNtlVlm': '2.4e9'},
       {'funding': '0.00002', 'openInterest': '3000000000', 'markPx': '0.01', 'prevDayPx': '0.0095', 'dayNtlVlm': '5e7'},
       {'funding': '0.0000419', 'openInterest': '2800000', 'markPx': '22.4', 'prevDayPx': '26.2', 'dayNtlVlm': '2e7'},
       {'funding': '0.01', 'openInterest': '1', 'markPx': '1', 'prevDayPx': '1', 'dayNtlVlm': '1'}]]
CG = [{'id': 'meme-token', 'name': 'Meme', 'market_cap': 3.25e10, 'market_cap_change_24h': -1.9, 'volume_24h': 2.5e9},
      {'id': 'pump-fun', 'name': 'Pump.fun Ecosystem', 'market_cap': 1.32e9, 'market_cap_change_24h': -5.0, 'volume_24h': 1.7e8},
      {'id': 'layer-1', 'name': 'Layer 1', 'market_cap': 2e12, 'market_cap_change_24h': 1, 'volume_24h': 1e11}]
PM_MARKETS = [
    {'question': 'Will Pedro Sanchez be the next Prime Minister of Spain?', 'outcomes': '["Yes", "No"]',
     'outcomePrices': '["0.22", "0.78"]', 'oneDayPriceChange': 0.04, 'volume24hr': 74000, 'events': [{}]},
    {'question': 'LoL: NaVi vs JDG (BO3)', 'outcomes': '["NaVi", "JDG"]', 'outcomePrices': '["0.5", "0.5"]',
     'oneDayPriceChange': 0.4, 'volume24hr': 3e6, 'gameId': 1, 'events': [{}]},
    {'question': 'Bitcoin Up or Down - October 8, 3PM ET', 'outcomes': '["Yes", "No"]', 'outcomePrices': '["0.5", "0.5"]',
     'oneDayPriceChange': 0.3, 'volume24hr': 2e6, 'events': [{}]}]
PM_CRYPTO = [
    {'title': 'What price will Bitcoin hit in October?', 'volume24hr': 685000,
     'markets': [{'question': '↓ 80,000', 'groupItemTitle': '↓ 80,000', 'outcomes': '["Yes", "No"]',
                  'outcomePrices': '["0.78", "0.22"]', 'active': True}]},
    {'title': 'Bitcoin above ___ on October 8?', 'volume24hr': 954000,
     'markets': [{'question': '74,000', 'groupItemTitle': '74,000', 'outcomes': '["Yes", "No"]',
                  'outcomePrices': '["0.9995", "0.0005"]', 'active': True}]}]
HIST = [{'date': 1790812800 + 86400 * i, 'tvl': 6.5e9 + 1e7 * i} for i in range(9)]
STABLE_CHAINS = [{'name': 'Solana', 'totalCirculatingUSD': {'peggedUSD': 1.629e10}},
                 {'name': 'Base', 'totalCirculatingUSD': {'peggedUSD': 5.16e9}}]
DEXS = {'total24h': 2.2e9, 'change_1d': 7.5, 'change_7d': -14.2,
        'protocols': [{'name': 'PumpSwap', 'total24h': 2.8e8, 'change_1d': -7.4}, {'name': 'Orca DEX', 'total24h': 2.6e8, 'change_1d': -10}]}

PM_TGE = [
    {'title': 'Variational FDV above ___ one day after launch?', 'volume24hr': 172708,
     'markets': [{'groupItemTitle': '$500M', 'outcomes': '["Yes", "No"]', 'outcomePrices': '["0.99", "0.01"]', 'active': True},
                 {'groupItemTitle': '$1B', 'outcomes': '["Yes", "No"]', 'outcomePrices': '["0.62", "0.38"]', 'active': True},
                 {'groupItemTitle': '$3B', 'outcomes': '["Yes", "No"]', 'outcomePrices': '["0.12", "0.88"]', 'active': True}]},
    {'title': 'Bitcoin above ___ on October 8?', 'volume24hr': 954000,
     'markets': [{'groupItemTitle': '74,000', 'outcomes': '["Yes", "No"]', 'outcomePrices': '["0.5", "0.5"]', 'active': True}]},
    {'title': 'Will Predict.fun launch a token by ___?', 'volume24hr': 12413,
     'markets': [{'groupItemTitle': 'November 30, 2026', 'outcomes': '["Yes", "No"]', 'outcomePrices': '["0.43", "0.57"]', 'active': True}]}]

ALL = {'closed=false&limit=100': PM_TGE, 'yields.llama.fi/pools': YIELDS, 'overview/open-interest': OI, 'api.llama.fi/protocols': PROTOCOLS,
       'overview/fees': FEES, 'hyperliquid.xyz/info': HL, 'coins/categories': CG, 'gamma-api.polymarket.com/markets': PM_MARKETS,
       'tag_slug=crypto': PM_CRYPTO, 'historicalChainTvl': HIST, 'stablecoinchains': STABLE_CHAINS, 'overview/dexs/': DEXS}

LANE_OF = {sid: route['beats'][0] for sid in lane_data.FETCHERS for route in [source_routes.route(sid)]}


@pytest.mark.parametrize('sid', sorted(lane_data.FETCHERS))
def test_every_lane_fetcher_parses_fixture_and_is_on_lane(sid):
    out = lane_data.FETCHERS[sid](transport=fake(ALL), now=NOW)
    assert out['status'] == 'ok', out
    src = out['sources'][0]
    assert src['source_id'] == sid and src['id'] == f'{sid}-2026-10-09'          # Beijing drafting day
    assert src['url'].endswith('#2026-10-09')                                    # filter_known must not skip tomorrow's
    assert len(out['units']) == out['rows'] >= 1                                 # every row validated into a unit
    assert all(u['numbers'] for u in out['units'])
    text = src['original_text']
    assert '0x' not in text
    assert lane_fit.lane_hits(LANE_OF[sid], text), (sid, text)                    # lane_fit accepts the packet


def test_yield_movers_skip_new_pools_and_non_stables():
    text = lane_data.yield_movers(transport=fake(ALL), now=NOW)['sources'][0]['original_text']
    assert 'morpho-blue USDC' in text and '-4.50 pp' in text and 'jupiter-lend PYUSD' in text
    assert 'USAT' not in text and 'STETH' not in text


def test_pendle_uses_pt_pools_and_lists_rwa():
    text = lane_data.pendle_stable(transport=fake(ALL), now=NOW)['sources'][0]['original_text']
    assert 'PT-USDai-15OCT2026' in text and 'fixed APY 11.37%' in text and 'For LP' not in text
    assert 'SUSDE' in text and 'Tokenized treasury (RWA) fund USDY' in text


def test_hyperliquid_funding_is_annualised_and_delisted_skipped():
    out = lane_data.hyperliquid_perps(transport=fake(ALL), now=NOW, min_oi=1e6)
    text = out['sources'][0]['original_text']
    assert 'Hyperliquid BTC perp' in text and '+11.0% annualised' in text   # 0.00125%/h x 24 x 365
    assert 'OLD' not in text
    meme = lane_data.hyperliquid_meme(transport=fake(ALL), now=NOW)['sources'][0]['original_text']
    assert 'kPEPE' in meme and 'BTC' not in meme and 'Memecoin perps on Hyperliquid' in meme


def test_tokenless_excludes_exchanges_and_tokens():
    text = lane_data.tokenless_tvl(transport=fake(ALL), now=NOW, min_tvl=5e7)['sources'][0]['original_text']
    assert 'Symbiotic' in text and 'Variational' not in text       # perp venues live in the OI watchlist only
    assert 'Binance' not in text and 'Kamino' not in text
    act = lane_data.tokenless_activity(transport=fake(ALL), now=NOW)['sources'][0]['original_text']
    assert 'Variational' in act and 'Kalshi' not in act and 'Hyperliquid' not in act


def test_polymarket_movers_and_crypto_skip_sports_intraday_and_settled():
    mv = lane_data.polymarket_movers(transport=fake(ALL), now=NOW)['sources'][0]['original_text']
    assert 'Pedro Sanchez' in mv and '+4 pts' in mv and 'NaVi' not in mv and 'Up or Down' not in mv
    cr = lane_data.polymarket_crypto(transport=fake(ALL), now=NOW)['sources'][0]['original_text']
    assert '78%' in cr and '74,000' not in cr


def test_polymarket_tge_takes_the_live_rung_and_skips_non_launch_events():
    text = lane_data.polymarket_tge(transport=fake(ALL), now=NOW)['sources'][0]['original_text']
    assert '"Variational FDV above ___ one day after launch?"' in text and '"$1B" at 62%' in text
    assert '$500M' not in text and 'Bitcoin' not in text
    assert '"November 30, 2026" at 43%' in text and 'TGE' in text


def test_solana_and_base_are_separate_chain_snapshots():
    sol = lane_data.solana_chain(transport=fake(ALL), now=NOW)
    base = lane_data.base_chain(transport=fake(ALL), now=NOW)
    st, bt = sol['sources'][0]['original_text'], base['sources'][0]['original_text']
    assert 'on Solana' in st and 'Base' not in st and 'on Base' in bt and 'Solana' not in bt
    assert sol['sources'][0]['url'] != base['sources'][0]['url']
    assert '$16.29bn' in st and '$5.16bn' in bt


def test_snapshot_urls_are_distinct():
    urls = [lane_data.FETCHERS[sid](transport=fake(ALL), now=NOW)['sources'][0]['url'] for sid in lane_data.FETCHERS]
    assert len(urls) == len(set(urls))          # hotspot links same-URL materials into one event


def test_http_failure_is_a_status_not_an_exception():
    out = lane_data.perp_oi(transport=lambda url, headers: (402, ''), now=NOW)
    assert out['status'] == 'http_402' and out['units'] == []


def test_disk_cache_serves_second_call(tmp_path, monkeypatch):
    calls = []

    class R:
        status_code, text = 200, json.dumps(OI)
    import httpx
    monkeypatch.setattr(lane_data, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(lane_data, 'MIN_GAP_S', 0)
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: calls.append(a) or R())
    assert lane_data.get_json(lane_data.OI)[0] == 200
    assert lane_data.get_json(lane_data.OI)[0] == 200
    assert len(calls) == 1


def test_lane_sources_routed_and_licensed():
    accounts = set()
    for sid in list(lane_data.FETCHERS) + list(lane_flashes.SOURCE_ID.values()):
        r = source_routes.route(sid)
        assert r and r['beats'], sid
        assert registry.source_licence_tier(sid) == 'B', sid
        accounts |= set(r['accounts'])
    assert accounts == {'crypto_meme_zh', 'crypto_meme_en', 'crypto_airdrop_zh', 'crypto_airdrop_en',
                        'crypto_prediction_zh', 'crypto_prediction_en', 'crypto_stable_yield_zh',
                        'crypto_stable_yield_en', 'crypto_perp_dex_en', 'sol_base_alpha_en'}
    # lane flash rows carry no name: the credit is the outlet in source.publisher
    from live import attribution_frame
    assert attribution_frame.publisher_name('lane_flash_meme') is None


RSS = '''<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>pump.fun 24 小时收入回升至 240 万美元</title><description>&lt;p&gt;据 DefiLlama 数据，meme 币发射台 pump.fun 收入回升。&lt;/p&gt;</description>
<link>https://x.example/1</link><pubDate>Thu, 08 Oct 2026 13:40:23 GMT</pubDate></item>
<item><title>某项目公布空投查询页面，快照已完成</title><description>空投总量占 10%。</description>
<link>https://x.example/2</link><pubDate>Thu, 08 Oct 2026 12:00:00 GMT</pubDate></item>
<item><title>美股三大指数集体低开</title><description>道指跌 0.36%。</description>
<link>https://x.example/3</link><pubDate>Thu, 08 Oct 2026 13:30:00 GMT</pubDate></item>
<item><title>新 meme 币上线，合约地址：7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU</title><description>冲</description>
<link>https://x.example/4</link><pubDate>Thu, 08 Oct 2026 13:00:00 GMT</pubDate></item>
<item><title>Catcher Predict：比赛胜者胜率暴跌 43%</title><description>预测市场 Polymarket 上</description>
<link>https://x.example/5</link><pubDate>Thu, 08 Oct 2026 13:00:00 GMT</pubDate></item>
<item><title>老新闻 Polymarket 交易量</title><description>预测市场</description>
<link>https://x.example/6</link><pubDate>Mon, 05 Oct 2026 13:00:00 GMT</pubDate></item>
</channel></rss>'''


def test_lane_flashes_filter_and_route():
    since = datetime(2026, 10, 7, 20, tzinfo=timezone.utc)
    out = lane_flashes.fetch('crypto_odaily_flash', since=since, now=NOW, transport=lambda u, h: (200, RSS))
    by = {s['url'][-1]: s for s in out['sources']}
    assert set(by) == {'1', '2'}                                  # macro tick, CA shill, sports odds, stale dropped
    assert by['1']['source_id'] == 'lane_flash_meme' and by['2']['source_id'] == 'lane_flash_airdrop'
    assert by['1']['publisher'] == 'Odaily 星球日报' and by['1']['no_reproduction'] is True
    assert lane_flashes.classify('智能合约平台上线新功能，比特币')[0] is None    # 智能合约 is not a perp story
    assert lane_flashes.classify('Hyperliquid 资金费率转负，比特币')[0] == 'crypto_perp'


def _src(i, lane, ts='2026-10-08T12:00:00+00:00'):
    import hashlib
    words = ' '.join(hashlib.md5(f'{lane}{i}{j}'.encode()).hexdigest()[:7] for j in range(6))   # distinct events
    return {'id': f'lf-{lane}-{i}', 'source_id': lane, 'original_text': f'{lane} {words}',
            'published_at': ts, 'also_reported_by': [], 'url': f'https://x/{lane}/{i}', 'adapter': 'lane_flash:t'}


def test_gather_balances_lanes_caps_and_skips_seen():
    def fetch(cid, since=None, now=None):
        if cid != 'crypto_odaily_flash':
            return {'status': 'ok', 'sources': [], 'items': 0}
        return {'status': 'ok', 'items': 30,
                'sources': [_src(i, 'lane_flash_perp') for i in range(12)] + [_src(i, 'lane_flash_meme') for i in range(3)]}
    state = {'lane_flashes': {'seen': ['lf-lane_flash_perp-0']}}
    plan = lane_sources.gather(state, now=NOW, fetch=fetch, flash_max=8, per_lane=5)
    assert len(plan['selected']) == 8
    assert plan['by_lane'] == {'lane_flash_perp': 5, 'lane_flash_meme': 3}
    assert 'lf-lane_flash_perp-0' not in {s['id'] for s in plan['selected']}


class FakeBudget:
    class BudgetExceeded(Exception):
        pass

    def __init__(self):
        self.cap, self.used, self.caps = 10.0, 1.0, []

    def spent(self):
        return self.used

    def set_cap(self, c):
        self.cap = c
        self.caps.append(c)


class FakeDB:
    def __init__(self):
        self.added, self.tags = [], {}

    def add(self, s, units, **kw):
        self.added += units
        return {'added': len(units), 'duplicate': 0, 'duplicate_content': 0}

    def set_persona_tags(self, tags, threshold=.7):
        self.tags.update(tags)


def test_extract_inside_ring_fence_tags_route_beats_and_defers_over_budget():
    budget, db = FakeBudget(), FakeDB()
    sel = [_src(i, 'lane_flash_airdrop') for i in range(3)]
    calls = []

    def batch(group, client, licence_tier, stats):
        calls.append(len(group))
        if len(calls) > 1:
            raise budget.BudgetExceeded('fence')
        budget.used += 0.01
        return {s['id']: [{'unit_id': 'u' + s['id'], 'statement': 'x'}] for s in group}
    state = {}
    stats = lane_sources.extract(db, sel, client=None, budget=budget, cost_cap_usd=10.0, fence_usd=0.25, state=state,
                                 now=NOW, extract_batch=batch, batch_size=2)
    assert budget.caps[0] == pytest.approx(1.25) and budget.caps[-1] == 10.0   # fence set, then restored
    assert stats['extracted'] == 2 and stats['deferred_budget'] == 1 and stats['units_added'] == 2
    assert stats['cost_usd'] == pytest.approx(0.01)
    assert all('crypto_airdrop' in t for t in db.tags.values()) and len(db.tags) == 2
    assert len(state['lane_flashes']['seen']) == 2


def test_supersede_keeps_only_newest_snapshot(tmp_path):
    rows = [{'unit_id': f'{sid}-{d}-{k}', 'source': {'source_id': sid, 'id': f'{sid}-{d}', 'published_at': f'2026-10-0{d}T22:00:00+00:00'}}
            for sid in ('hyperliquid_perps', 'x_other', 'defillama_sol_base_tvl') for d in (7, 8) for k in range(2)]
    (tmp_path / 'units.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
    out = lane_sources.supersede_snapshots(tmp_path)
    assert out == {'hyperliquid_perps': 2, 'defillama_sol_base_tvl': 4}     # retired source: every unit goes
    supp = {json.loads(l)['unit_id'] for l in (tmp_path / 'suppressed.jsonl').read_text().splitlines()}
    assert supp == {'hyperliquid_perps-7-0', 'hyperliquid_perps-7-1'} | {f'defillama_sol_base_tvl-{d}-{k}' for d in (7, 8) for k in range(2)}
    assert lane_sources.supersede_snapshots(tmp_path) == {}                # idempotent


def test_switches(monkeypatch):
    from live import daily_ingest
    keys = [k for k in daily_ingest.default_fetchers({'channels': {}}) if k.startswith('lanes:')]
    assert set(keys) == {'lanes:polymarket_markets', 'lanes:defillama_yields'} | {'lanes:' + s for s in lane_data.FETCHERS}
    monkeypatch.setenv('FD_LANE_DATA_SOURCES', '0')
    keys = [k for k in daily_ingest.default_fetchers({'channels': {}}) if k.startswith('lanes:')]
    assert keys == ['lanes:polymarket_markets', 'lanes:defillama_yields']
    assert lane_sources.flashes_enabled({'FD_LANE_FLASHES': '0'}) is False
    monkeypatch.setenv('FD_LANE_FLASH_BUDGET_USD', '0.1')
    assert lane_sources.budget_usd() == 0.1


def test_lane_fit_accepts_routed_snapshot_for_niche_account():
    acct = {'id': 'crypto_airdrop_en', 'lane_first': True, 'retrieval_beats': ['crypto_airdrop', 'crypto_defi']}
    text = lane_data.tokenless_tvl(transport=fake(ALL), now=NOW, min_tvl=5e7)['sources'][0]['original_text']
    assert lane_fit.packet_check(acct, text)['ok']


def test_hotspot_does_not_chain_lane_snapshots_by_coincidental_numbers():
    from live import hotspot as H

    def m(i, sid, text, adapter=None, url=''):
        g = [{'unit_id': f'u{i}', 'licence_tier': 'B', 'unit': {'numbers': [], 'statement': text},
              'source': {'title': text[:40], 'publisher': 'DefiLlama', 'url': url, 'adapter': adapter or f'lane_data:{sid}',
                         'source_id': sid, 'id': f'{sid}-2026-10-09', 'source_hash': f'h{i}'}}]
        return H.material((f'h{i}', f'{sid}-2026-10-09'), g, text)

    sol = m(1, 'defillama_solana', 'Solana DeFi TVL per DefiLlama: $6.38bn (+7.5% 7d).', url='https://defillama.com/chain/Solana')
    air = m(2, 'defillama_tokenless', 'Airdrop watchlist Symbiotic per DefiLlama: $460m (+7.5% 7d).', url='https://defillama.com/airdrops')
    feed = m(3, 'x', 'DefiLlama: Symbiotic TVL $460m, up 7.5% this week', adapter='feed', url='https://x.com/a/1')
    other = m(4, 'y', 'DefiLlama shows Symbiotic TVL $460m, up 7.5%', adapter='feed', url='https://x.com/b/2')
    df = {'defillama': 9}
    assert H.link_reason(sol, air, df, 3) is None and H.link_reason(air, feed, df, 3) is None
    assert H.link_reason(feed, other, df, 3) == 'number+entity'          # ordinary stories still cluster
    same_url = m(5, 'defillama_base', 'Base chain DeFi TVL: $6.17bn', url='https://defillama.com/chain/Solana')
    assert H.link_reason(sol, same_url, df, 3) == 'url'
