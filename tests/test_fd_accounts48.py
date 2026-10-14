"""Oct 14: accounts 37-48 (group new12, live/fd_accounts_new12.json, FD_ACCOUNTS_NEW12 default 1)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT)]

from live import fd_accounts, registry, source_routes  # noqa: E402
from live.adapters import lane_data  # noqa: E402

NEW12 = ['options_vol_zh', 'funding_arb_zh', 'overseas_flash_zh', 'hk_us_ipo_zh', 'ai_techstocks_zh', 'exchange_perks_zh',
         'options_vol_en', 'yield_arb_en', 'crypto_equities_en', 'macro_en', 'onchain_daily_en', 'asia_news_en']


def test_roster_48_and_gate(monkeypatch):
    monkeypatch.delenv('FD_ACCOUNTS_NEW12', raising=False)
    rows = fd_accounts.load()
    assert len(rows) == 48 and [r['no'] for r in rows] == list(range(1, 49))
    assert [r['id'] for r in rows[36:]] == NEW12 and {r['group'] for r in rows[36:]} == {'new12'}
    assert [r['id'] for r in fd_accounts.load({'FD_ACCOUNTS_NEW12': '0'})] == [r['id'] for r in rows[:36]]


def test_new12_rows_complete():
    emotion = json.loads((ROOT / 'live/emotion_tiers.json').read_text())['personas']
    media = json.loads((ROOT / 'live/media_profiles.json').read_text())['accounts']
    licence = json.loads((ROOT / 'live/source_licence.json').read_text())['tiers']
    roster = json.loads((ROOT / 'live/donors/roster.json').read_text())
    for a in fd_accounts.load(groups=('new12',)):
        assert a['name'] and a['retrieval_beats'] and emotion.get(a['id']) and a['id'] in media, a['id']
        assert (ROOT / 'live/personas' / f"{a['id']}.json").exists(), a['id']
        assert len(roster['persona_clusters']['acct_' + a['id']]['donors']) >= registry.MIN_EXEMPLARS, a['id']
        assert 4 <= len(a['x_sources']['CORE']) <= 6 and not a['lane_first'] and a['lane_data'], a['id']
        for h in a['x_sources']['CORE']:
            assert licence['x_' + h]['tier'] in ('B', 'C'), h   # C (media, e.g. WuBlockchain): topic lead only
    assert 'x_0xdahua' not in licence


def test_new_lane_sources_routed_and_licensed():
    for sid, acc in (('deribit_options', {'options_vol_zh', 'options_vol_en'}), ('cex_funding', {'funding_arb_zh', 'yield_arb_en'}),
                     ('nasdaq_ipos', {'hk_us_ipo_zh'})):
        assert sid in lane_data.FETCHERS and registry.source_licence_tier(sid) == 'B'
        assert set(source_routes.route(sid)['accounts']) == acc


def test_deribit_and_funding_parse_offline():
    def transport(url, headers):
        if 'book_summary' in url:
            return 200, json.dumps({'result': [{'instrument_name': 'BTC-1-C', 'open_interest': 100, 'underlying_price': 60000, 'volume': 10},
                                               {'instrument_name': 'BTC-1-P', 'open_interest': 50, 'underlying_price': 60000, 'volume': 5}]})
        if 'volatility_index' in url:
            return 200, json.dumps({'result': {'data': [[0, 1, 1, 1, 40.0], [1, 1, 1, 1, 44.0]]}})
        if 'binance' in url:
            return 200, json.dumps({'lastFundingRate': '0.0001'})
        return 404, ''
    r = lane_data.deribit_options(transport=transport)
    assert r['rows'] >= 2 and any('put/call OI ratio 0.50' in u['statement'] for u in r['units'])
    f = lane_data.cex_funding(transport=transport)
    assert f['rows'] == 2 and 'Binance +11.0%' in f['units'][0]['statement']
