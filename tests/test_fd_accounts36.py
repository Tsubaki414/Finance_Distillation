"""Oct 8: 36 accounts (20 mains + 6 spares + 10 new) - roster gates, lanes, risk rules, structured lane sources,
lane-first selection, dashboard status, persona-factory helpers, media profiles --only-missing."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT)]

from live import beat_rules, editorial_style, fd_accounts, qa_levels, registry, risk_rules, topic_div  # noqa: E402


@pytest.fixture(autouse=True)
def _gates(monkeypatch):
    monkeypatch.delenv('FD_ACCOUNTS_EXTRA', raising=False)
    monkeypatch.delenv('FD_ACCOUNTS_NEW', raising=False)


# ---------------------------------------------------------------- roster

def test_roster_groups_and_gates():
    rows = fd_accounts.load()
    assert len(rows) == 36 and len({r['id'] for r in rows}) == 36
    assert [r['no'] for r in rows] == list(range(1, 37))
    assert {r['group'] for r in rows[:20]} == {'main'} and {r['group'] for r in rows[20:26]} == {'spare'}
    assert {r['status'] for r in rows[26:]} == {'new'} and {r['status'] for r in rows[20:26]} == {'spare_active'}
    assert len(fd_accounts.load({'FD_ACCOUNTS_NEW': '0'})) == 26
    assert len(fd_accounts.load({'FD_ACCOUNTS_EXTRA': '0'})) == 30
    assert [r['id'] for r in fd_accounts.load({'FD_ACCOUNTS_EXTRA': '0', 'FD_ACCOUNTS_NEW': '0'})] == \
        [r['id'] for r in json.loads(fd_accounts.MAIN.read_text())['accounts']]
    assert sum(r['lang'] == 'zh' for r in rows[26:]) == 5   # 5 zh / 5 en new accounts


def test_rows_default_path_is_roster_other_path_is_that_file(tmp_path, monkeypatch):
    assert len(fd_accounts.rows()) == 36 and len(fd_accounts.rows(fd_accounts.MAIN)) == 36
    monkeypatch.setenv('FD_ACCOUNTS_NEW', '0')
    assert len(fd_accounts.rows(fd_accounts.MAIN)) == 26
    f = tmp_path / 'a.json'
    f.write_text(json.dumps({'accounts': [{'id': 'x', 'lang': 'en'}]}))
    assert fd_accounts.rows(f) == [{'id': 'x', 'lang': 'en'}]


def test_extra_and_new_rows_are_complete():
    emotion = json.loads((ROOT / 'live/emotion_tiers.json').read_text())['personas']
    media = json.loads((ROOT / 'live/media_profiles.json').read_text())['accounts']
    licence = json.loads((ROOT / 'live/source_licence.json').read_text())['tiers']
    roster = json.loads((ROOT / 'live/donors/roster.json').read_text())
    for a in fd_accounts.load(groups=('spare', 'new')):
        assert a['retrieval_beats'] and a['emotion_tier'] in ('low', 'mid', 'high'), a['id']
        assert emotion.get(a['id']), a['id']
        assert a['id'] in media, a['id']
        assert len(a['donors']) >= registry.MIN_EXEMPLARS, a['id']
        assert (ROOT / 'live/personas' / f"{a['id']}.json").exists(), a['id']
        cluster = roster['persona_clusters']['acct_' + a['id']]
        assert {d['handle'] for d in cluster['donors']} == set(a['donors']), a['id']
        for h in a['x_sources']['CORE'] + a['x_sources']['SECONDARY']:
            assert licence['x_' + h]['tier'] == 'B', h
        if a['group'] == 'new':
            assert a['lane_first'] and a['risk_rules'] and a['does_not_write'] and a['positioning']
            assert set(a['donor_evidence']) == set(a['donors'])
            assert all(e['last_post'] >= '2026-09-08' for e in a['donor_evidence'].values())   # active in 30 days
            for h in a['donors']:
                assert roster['donors'][h.lower()]['donor_fit'] == 'voice'
    assert 'x_0xdahua' not in licence   # promo-heavy roster exclude: neither donor nor X source


def test_new_personas_validate():
    personas = registry.load_personas()
    for a in fd_accounts.load(groups=('spare', 'new')):
        assert registry.persona_for_account(a['id'], personas).lang == a['lang']


# ---------------------------------------------------------------- lanes

def test_new_lane_keywords():
    kb = beat_rules.keyword_beats
    assert 'crypto_prediction' in kb('Polymarket odds on a Fed cut jumped to 80%')
    assert 'crypto_prediction' in kb('Kalshi volume hit a record this week')
    assert 'crypto_prediction' not in kb('the odds are that bitcoin rises')          # odds alone is not the lane
    assert 'crypto_stable_yield' in kb('Ethena USDe yield fell to 5% APY')            # USDe is crypto enough
    assert 'crypto_stable_yield' in kb('稳定币理财年化 8% 的产品要看收益从哪来')
    assert 'crypto_stable_yield' not in kb('Aave lending yield on ETH')               # no stablecoin word
    assert 'ipo' in kb('某公司港股招股，认购倍数 300 倍，暗盘涨 20%')
    assert 'ipo' in kb('Stripe is going public via an IPO') and 'ipo' not in kb('the debut album sold well')


def test_lane_tags_adds_only_missing_new_lanes():
    rows = [{'unit_id': 'a', 'unit': {'statement': 'Polymarket gives a 70% chance of a cut'}, 'persona_tags': {}},
            {'unit_id': 'b', 'unit': {'statement': 'Stripe files for an IPO'},
             'persona_tags': {'ipo': {'verdict': 'relevant', 'confidence': 0.9}}},
            {'unit_id': 'c', 'unit': {'statement': 'Nothing here'}, 'persona_tags': {}}]
    out = beat_rules.lane_tags(rows)
    assert set(out) == {'a'} and out['a']['crypto_prediction']['rule'].endswith(':lane')


def test_jev_front_lanes_and_account_mapping():
    from live.jev_front import KEYWORD_LANES, LANE_BEATS, PERSONA_FOR_ACCOUNT, PERSONAS, SUB_BEATS
    assert {'crypto_prediction', 'crypto_stable_yield'} <= set(SUB_BEATS) and 'ipo' in KEYWORD_LANES
    assert set(LANE_BEATS) <= set(PERSONAS)
    assert PERSONA_FOR_ACCOUNT['zh_hk_ipo'] == 'zh_us_stock_commentary'
    assert PERSONA_FOR_ACCOUNT['crypto_meme_en'] == 'crypto_macro_en'


def test_topic_div_new_themes():
    assert topic_div.themes_of('港股打新 认购 300 倍 暗盘')[0] == 'ipo'
    assert topic_div.themes_of('Polymarket odds jumped')[0] == 'c_prediction'
    assert topic_div.THEMES[-1] == 'other'


# ---------------------------------------------------------------- beat gate

def test_beat_gate_prediction_crossover_and_ipo():
    rows = fd_accounts.by_id()
    assert editorial_style.beat_gate(rows['crypto_prediction_en'], 'Kalshi and Polymarket disagree on the Fed')[0]
    assert editorial_style.beat_gate(rows['crypto_ai_crossover_zh'], '英伟达数据中心收入创新高')[0]
    assert not editorial_style.beat_gate(rows['crypto_newbie_zh'], '英伟达数据中心收入创新高')[0]
    assert not editorial_style.beat_gate(rows['zh_hk_ipo'], '比特币 ETF 流入，以太坊质押')[0]
    assert editorial_style.beat_gate(rows['zh_hk_ipo'], '港股打新：认购 300 倍')[0]


# ---------------------------------------------------------------- risk rules

@pytest.mark.parametrize('text,codes', [
    ('这个币 CA: 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU 冲', {'contract_address'}),
    ('合约地址：0x1234567890abcdef1234567890abcdef12345678', {'contract_address'}),
    ('稳定币理财没有保本这回事，收益都有来源', set()),
    ('这个池子号称保本，实际是借给高杠杆玩家', set()),
    ('This is the next 100x for sure', {'guaranteed_return'}),
    ('Guaranteed returns of 20% APY', {'guaranteed_return'}),
    ('There is no risk-free yield in DeFi', set()),
    ('Hyperliquid offers 100x leverage on BTC', set()),
    ('某项目白名单开了，赶紧冲', {'scam_promotion'}),
    ('项目方靠白名单冲量', set()),
    ('邀请码填我的', {'referral_link'}),
    ('pump.fun 上周发了 2 万个新币，存活率不到 1%', set()),
])
def test_risk_rules(text, codes):
    lang = 'zh' if any(ord(c) > 255 for c in text) else 'en'
    assert {f['code'] for f in risk_rules.findings(text, lang)} == codes


def test_risk_codes_are_hard_with_fixes():
    for code in risk_rules.HARD_CODES:
        assert code in qa_levels.HARD and qa_levels.FIXES.get(code)


# ---------------------------------------------------------------- structured lane sources

POLY = [{'title': 'Fed Decision in October?', 'volume24hr': 1500000, 'tags': [{'slug': 'economy'}],
         'markets': [{'question': 'No change', 'groupItemTitle': 'No change', 'outcomes': '["Yes", "No"]',
                      'outcomePrices': '["0.86", "0.14"]', 'active': True},
                     {'question': '25 bps cut', 'groupItemTitle': '25 bps cut', 'outcomes': '["Yes", "No"]',
                      'outcomePrices': '["0.12", "0.88"]', 'active': True}]},
        {'title': 'Lakers vs Celtics', 'volume24hr': 9e6, 'tags': [{'slug': 'nba'}],
         'markets': [{'question': 'Lakers', 'outcomes': '["Yes", "No"]', 'outcomePrices': '["0.5", "0.5"]'}]},
        {'title': 'Elon Musk # tweets this week?', 'volume24hr': 2e6, 'tags': [],
         'markets': [{'question': '0-19', 'outcomes': '["Yes", "No"]', 'outcomePrices': '["0.3", "0.7"]'}]}]


def _fake(body):
    return lambda url, headers: (200, json.dumps(body))


def test_polymarket_adapter_skips_sports_and_tweet_markets():
    from datetime import datetime, timezone
    from live.adapters import polymarket
    out = polymarket.fetch(transport=_fake(POLY), now=datetime(2026, 10, 8, tzinfo=timezone.utc))
    assert out['status'] == 'ok' and len(out['units']) == 1
    line = out['units'][0]['statement']
    assert line == 'Polymarket "Fed Decision in October?", 2026-10-08: "Yes" on "No change" trades at 86%; 24h volume $1.5m.'
    assert {n['text'] for n in out['units'][0]['numbers']} == {'86%', '$1.5m'}


def test_defillama_yields_adapter():
    from datetime import datetime, timezone
    from live.adapters import defillama_yields
    data = {'data': [{'chain': 'Ethereum', 'project': 'sky-lending', 'symbol': 'SUSDS', 'tvlUsd': 4.9e9, 'apy': 3.8,
                      'apyMean30d': 3.6, 'stablecoin': True, 'exposure': 'single'},
                     {'chain': 'Ethereum', 'project': 'tiny', 'symbol': 'USDC', 'tvlUsd': 5e6, 'apy': 40,
                      'stablecoin': True, 'exposure': 'single'},
                     {'chain': 'Ethereum', 'project': 'lido', 'symbol': 'STETH', 'tvlUsd': 2e10, 'apy': 3,
                      'stablecoin': False, 'exposure': 'single'}]}
    out = defillama_yields.fetch(transport=_fake(data), now=datetime(2026, 10, 8, tzinfo=timezone.utc))
    texts = [u['statement'] for u in out['units']]
    assert len(texts) == 2 and '3.80%' in texts[0] and 'sky-lending SUSDS' in texts[1] and 'tiny' not in ' '.join(texts)


def test_nasdaq_ipo_adapter_and_timeout():
    from datetime import datetime, timezone
    from live.adapters import nasdaq_ipo
    body = {'data': {'priced': {'rows': [{'companyName': 'Pine Tree Acquisition Corp.', 'proposedTickerSymbol': 'PAXGU',
                                          'proposedExchange': 'NASDAQ Global', 'proposedSharePrice': '10.00',
                                          'pricedDate': '10/06/2026', 'dollarValueOfSharesOffered': '$100,000,000'}]},
                     'upcoming': {'upcomingTable': {'rows': []}}}}
    out = nasdaq_ipo.fetch(transport=_fake(body), now=datetime(2026, 10, 8, tzinfo=timezone.utc))
    assert len(out['units']) == 1 and 'Pine Tree' in out['units'][0]['statement']

    def boom(url, headers):
        raise TimeoutError('read timeout')
    assert nasdaq_ipo.fetch(transport=boom)['status'].startswith('error')


def test_lane_sources_are_routed_and_licensed():
    from live import source_routes
    for sid, accounts, beat in (('polymarket_markets', {'crypto_prediction_zh', 'crypto_prediction_en'}, 'crypto_prediction'),
                                ('defillama_yields', {'crypto_stable_yield_zh', 'crypto_stable_yield_en'}, 'crypto_stable_yield'),
                                ('nasdaq_ipo_calendar', {'zh_hk_ipo'}, 'ipo')):
        r = source_routes.route(sid)
        assert set(r['accounts']) == accounts and r['beats'] == (beat,)
        assert registry.source_licence_tier(sid) == 'B'


def test_daily_ingest_lane_fetchers_gated(monkeypatch):
    from live import daily_ingest
    keys = [k for k in daily_ingest.default_fetchers({'channels': {}}) if k.startswith('lanes:')]
    assert keys == ['lanes:polymarket_markets', 'lanes:defillama_yields', 'lanes:nasdaq_ipo_calendar']
    monkeypatch.setenv('FD_ACCOUNTS_NEW', '0')
    assert not [k for k in daily_ingest.default_fetchers({'channels': {}}) if k.startswith('lanes:')]


# ---------------------------------------------------------------- selection

def _rec(uid, adapter, tags=(), source_id=None):
    return {'unit_id': uid, 'unit': {'kind': 'fact', 'statement': uid}, 'tag_personas': list(tags),
            'source': {'id': uid, 'source_hash': uid, 'adapter': adapter, 'source_id': source_id or uid}}


def test_lane_first_order(monkeypatch):
    import daily_compose as dc
    acct = {'id': 'crypto_meme_en', 'lane_first': True, 'retrieval_beats': ['crypto_meme', 'crypto_macro_en']}
    groups = [[_rec('news', 'rss')], [_rec('lane', 'rss', tags=['crypto_meme'])], [_rec('own', 'x:Overdose_AI')],
              [_rec('other_x', 'x:someone')]]
    assert [g[0]['unit_id'] for g in dc.lane_first(acct, groups, ['Overdose_AI'])] == ['lane', 'own', 'news', 'other_x']
    assert dc.lane_first({**acct, 'lane_first': False}, groups, ['Overdose_AI']) == groups
    monkeypatch.setenv('FD_LANE_FIRST', '0')
    assert dc.lane_first(acct, groups, ['Overdose_AI']) == groups


def test_routed_data_packets_only_for_routed_lane_first_accounts(monkeypatch):
    from datetime import datetime, timezone
    import daily_compose as dc
    from live.adapters import polymarket
    out = polymarket.fetch(transport=_fake(POLY), now=datetime(2026, 10, 8, tzinfo=timezone.utc))
    src = out['sources'][0]
    group = [{'unit_id': u['unit_id'], 'unit': u, 'source': src, 'tag_personas': ['crypto_prediction']}
             for u in out['units']]
    rows = fd_accounts.by_id()
    assert dc.routed_data_packets([group], 'crypto_prediction_en', rows['crypto_prediction_en']) == [group]
    assert dc.routed_data_packets([group], 'crypto_meme_en', rows['crypto_meme_en']) == []        # not routed
    assert dc.routed_data_packets([group], 'crypto_prediction_en', {'lane_first': False}) == []
    monkeypatch.setenv('FD_LANE_DATA', '0')
    assert dc.routed_data_packets([group], 'crypto_prediction_en', rows['crypto_prediction_en']) == []


def test_x_subscriptions_skip_gated_off_groups(monkeypatch):
    from live import x_daily
    uni = {'crypto_macro_en': {'x_sources': [{'handle': 'a', 'enabled': True}]},
           'crypto_meme_en': {'group': 'new', 'x_sources': [{'handle': 'b', 'enabled': True}]}}
    monkeypatch.setenv('FD_ACCOUNTS_NEW', '0')
    subs = x_daily.subscriptions(universes=uni, config=fd_accounts.load(), breadth=[])
    assert [s['handle'] for s in subs] == ['a']
    monkeypatch.delenv('FD_ACCOUNTS_NEW')
    subs = x_daily.subscriptions(universes=uni, config=fd_accounts.load(), breadth=[])
    assert sorted(s['handle'] for s in subs) == ['a', 'b']


# ---------------------------------------------------------------- dashboard / admin

def test_ops_dashboard_accounts_carry_status_and_times():
    import build_ops_dashboard as ops
    accts = ops.load_accounts()
    assert len(accts) == 36
    status = {a['id']: a['status'] for a in accts}
    assert status['crypto_meme_zh'] == 'new' and status['zh_macro'] == 'spare_active' and status['zh_industry'] == 'main'
    drafts = [{'id': f'd{i}', 'account_id': 'crypto_meme_zh', 'time': f'2026-10-09T0{i}:00:00+08:00'} for i in (1, 2)]
    out = ops.clamp_times(drafts, '2026-10-09')
    t = sorted(d['time'][11:16] for d in out)
    assert '08:00' <= t[0] and t[-1] <= '22:59'
    assert 'spare_active' in ops.PAGE and '新号' in ops.PAGE


def test_admin_console_shows_status():
    import build_admin_console as adm
    src = Path(adm.__file__).read_text()
    assert "'status')} for a in ops.load_accounts()" in src and '新号' in src


# ---------------------------------------------------------------- persona factory helpers

def test_persona_factory_helpers(tmp_path, monkeypatch):
    import persona_factory as pf
    roster = {'donors': {'known': {'handle': 'Known', 'donor_fit': 'radar'}}, 'persona_clusters': {}}
    acct = {'id': 'crypto_meme_en', 'lang': 'en', 'retrieval_beats': ['crypto_meme'], 'group': 'new',
            'donor_evidence': {'Known': {}, 'Fresh': {'followers': 10, 'last_post': '2026-10-08', 'originals_scraped': 150}},
            'x_sources': {'CORE': ['Fresh'], 'SECONDARY': ['Side']}}
    assert pf.ensure_roster_donors(roster, acct)
    assert roster['donors']['fresh']['donor_fit'] == 'voice' and roster['donors']['known']['donor_fit'] == 'radar'
    assert not pf.ensure_roster_donors(roster, acct)
    assert pf.x_sources_of(acct, {}) == acct['x_sources']
    assert pf.x_sources_of({'id': 'zh_industry'}, {'accounts': {'zh_industry': {'x_sources': {'CORE': ['a']}}}}) == {'CORE': ['a']}
    lic = tmp_path / 'lic.json'
    lic.write_text(json.dumps({'tiers': {'x_Side': {'tier': 'C'}}}))
    monkeypatch.setattr(pf, 'LICENCE', lic)
    assert pf.register_x_sources([acct]) == ['Fresh']
    tiers = json.loads(lic.read_text())['tiers']
    assert tiers['x_Fresh']['tier'] == 'B' and tiers['x_Side']['tier'] == 'C'   # existing entries are never changed
    assert pf.register_x_sources([acct]) == []


def test_media_profiles_only_missing_keeps_existing(tmp_path, monkeypatch):
    import build_media_profiles as bmp
    out = tmp_path / 'media.json'
    fam = {'chart_share': 0.5, 'styles': {s: 0.2 for s in bmp.STYLES}, 'light_share': 0.5, 'tall_share': 0.1, 'n': 10}
    keep = {'version': 1, 'built': '2026-10-08', 'families': {'crypto_en': fam, 'crypto_zh': fam, 'stocks_en': fam,
                                                             'stocks_zh': fam},
            'accounts': {'crypto_macro_en': {'p_image': 0.123}}}
    out.write_text(json.dumps(keep))
    (tmp_path / 'classes.json').write_text('{}')
    (tmp_path / 'meta.json').write_text(json.dumps({'images': {}}))
    accts = tmp_path / 'accts.json'
    accts.write_text(json.dumps({'accounts': [{'id': 'crypto_macro_en', 'kind': 'crypto', 'lang': 'en'},
                                              {'id': 'crypto_meme_en', 'kind': 'crypto', 'lang': 'en'}]}))
    monkeypatch.setattr(bmp, 'image_rate', lambda aid, roster, posts: (0.4, 200))
    monkeypatch.setattr(sys, 'argv', ['x', '--classes', str(tmp_path / 'classes.json'), '--meta', str(tmp_path / 'meta.json'),
                                      '--accounts', str(accts), '--out', str(out), '--only-missing'])
    bmp.main()
    res = json.loads(out.read_text())
    assert res['accounts']['crypto_macro_en'] == {'p_image': 0.123}
    assert res['accounts']['crypto_meme_en']['p_image'] == round(0.4 * 0.5, 3)
    assert res['families'] == keep['families'] and list(res['added'].values()) == [['crypto_meme_en']]
