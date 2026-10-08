"""Oct 8 evening: event de-dup (1 account per language per 母题), same-conclusion arbitration across sources and runs,
niche-account lane fit, hook / forecast attribution / stale-claim checks, media priority + cold-start quote bias."""
import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from live import claim_arbitration as ca, cold_start, hook_voice as hv, lane_fit, post_mode, qa_levels

ROOT = Path(__file__).resolve().parents[1]
REF = datetime(2026, 10, 8, 22, 13, tzinfo=timezone.utc)


def _script(name):
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def hook_on(monkeypatch):
    monkeypatch.setenv('FD_HOOK_VOICE', '1')


# ------------------------------------------------------------------ 1. event cap + same-conclusion arbitration

def test_event_cap_is_one_account_per_language_by_default():
    from live import hotspot
    dc = _script('daily_compose')
    assert dc.MAX_ACCOUNTS_PER_EVENT == 1 and hotspot.MAX_PER_LANG == 1


def _cand(aid, view, lang, source, direction=None, body=''):
    return {'key': aid, 'account_id': aid, 'subject': '', 'direction': direction, 'account_view': view,
            'source_id': source, 'day': '2026-10-08', 'account_lang': lang, 'body': body}


SUPPORT_A = '比特币还没跌破关键支撑位，这次深度回调只是大牛市趋势里的正常震荡。'
SUPPORT_B = '比特币关键支撑位尚未跌破说明上升结构依然稳固，当前的深调属于牛市正常的价格震荡。'


def test_same_conclusion_from_different_sources_collides_only_when_enabled():
    a, b = _cand('crypto_onchain_zh', SUPPORT_A, 'zh', 's1'), _cand('crypto_trader_zh', SUPPORT_B, 'zh', 's2')
    assert not ca.claims_collide(a, b, same_language=True)                       # old rule: different sources pass
    assert ca.claims_collide(a, b, same_language=True, same_conclusion=True)
    dec = {d['account_id']: d['status'] for d in ca.arbitrate([a, b], same_language=True, same_conclusion=True)}
    assert sorted(dec.values()) == ['HOLD', 'WRITE']


def test_same_conclusion_keeps_disagreement_other_language_and_unrelated_takes():
    a = _cand('crypto_onchain_zh', SUPPORT_A, 'zh', 's1', direction='bullish')
    assert not ca.claims_collide(a, _cand('crypto_trader_zh', SUPPORT_B, 'zh', 's2', direction='bearish'),
                                 same_language=True, same_conclusion=True)
    assert not ca.claims_collide(a, _cand('crypto_macro_en', 'Bitcoin holds key support; this dip is normal.', 'en', 's3'),
                                 same_language=True, same_conclusion=True)
    tron = _cand('crypto_onchain_en', "Bitcoin and crypto serve as real-time gauges for global dollar liquidity.", 'en', 's4')
    drv = _cand('crypto_trader_en', '$DRV is bullish because its expansion into a new market is happening.', 'en', 's5')
    assert not ca.claims_collide(tron, drv, same_language=True, same_conclusion=True)


def test_shared_number_and_name_is_the_same_story():
    a = _cand('crypto_etf_flows_en', "Robinhood's treasury move signals deeper integration.", 'en', 's1',
              body="Robinhood just put $25 million of bitcoin on its balance sheet.")
    b = _cand('crypto_stable_yield_en', 'Corporate treasuries are pivoting to digital assets.', 'en', 's2',
              body='Robinhood bought $25 million in BTC for the treasury.')
    assert ca.claims_collide(a, b, same_language=True, same_conclusion=True)


def test_earlier_ready_draft_is_a_locked_keeper():
    new = [{'id': 'd2', 'account_id': 'crypto_trader_zh', 'source': {'id': 's2'}, 'day': '2026-10-08',
            'account_lang': 'zh', 'body': SUPPORT_B, 'stance': {'account_view': SUPPORT_B, 'view': {}}}]
    earlier = [{'id': 'd1', 'account_id': 'crypto_onchain_zh', 'lang': 'zh', 'day': '2026-10-08', 'body': SUPPORT_A,
                'stance': {'account_view': SUPPORT_A}, 'source': {'id': 's1'}}]
    out = ca.apply_to_results(new, same_language=True, same_conclusion=True, locked=earlier)
    assert len(out) == 1 and out[0]['arbitration']['status'] == 'HOLD'
    assert out[0]['arbitration']['reassigned_to'] == 'crypto_onchain_zh'
    alone = ca.apply_to_results(new, same_language=True, same_conclusion=True)
    assert alone[0]['arbitration']['status'] == 'WRITE'


def test_ready_events_carry_the_motif(monkeypatch):
    dc = _script('daily_compose')
    rows = [{'account_id': 'a', 'draft_status': 'draft_ready', 'text': 'x', 'body': 'x', 'angle': 'macro_liquidity',
             'source': {'id': 's1', 'title': 'short'}, 'hotspot': {'motif_id': 'm7'}}]
    monkeypatch.setattr(dc.compose_inbox, 'rows', lambda day: rows)
    ev = dc.ready_events(date(2026, 10, 9), [{'id': 'a', 'lang': 'en'}])
    assert (('motif', 'm7'), 'a', 'macro_liquidity', 'en') in ev


# ------------------------------------------------------------------ 2. lane fit

PERP = {'id': 'crypto_perp_dex_en', 'lane_first': True, 'retrieval_beats': ['crypto_perp', 'crypto_defi', 'crypto_macro_en']}
AIRDROP = {'id': 'crypto_airdrop_zh', 'lane_first': True, 'retrieval_beats': ['crypto_airdrop', 'crypto_defi', 'crypto_perp']}
SOLBASE = {'id': 'sol_base_alpha_en', 'lane_first': True, 'retrieval_beats': ['crypto_ecosystem_sol_base', 'crypto_defi']}
MACRO = {'id': 'crypto_macro_en', 'retrieval_beats': ['crypto_macro_en']}


def test_niche_accounts_and_primary_lanes():
    assert lane_fit.is_niche(PERP) and lane_fit.is_niche({'id': 'crypto_meme_zh'}) and not lane_fit.is_niche(MACRO)
    assert lane_fit.primary_lane(AIRDROP) == 'crypto_airdrop' and lane_fit.primary_lane(SOLBASE) == 'crypto_ecosystem_sol_base'


def test_packet_lane_gate():
    liq = 'Bitcoin briefly slides below $84,000 as crypto long liquidations reach $487 million'
    assert lane_fit.packet_check(PERP, liq)['ok']                                 # liquidations = perp lane
    assert not lane_fit.packet_check(AIRDROP, liq)['ok']                          # not an airdrop story
    assert not lane_fit.packet_check(AIRDROP, 'Bitcoin nears highest level since January as ETF inflows return')['ok']
    assert lane_fit.packet_check(AIRDROP, 'Linea 空投快照时间公布，积分规则调整')['ok']
    assert not lane_fit.packet_check(SOLBASE, "El Salvador: There's a new coin in town")['ok']
    assert lane_fit.packet_check(SOLBASE, 'Solana DEX volume tops Base for the third week')['ok']
    assert lane_fit.packet_check(AIRDROP, 'gm frens, farming a new testnet today', own_x=True)['ok']
    assert not lane_fit.packet_check(AIRDROP, 'Bitcoin ETF flows turned positive', own_x=True)['ok']
    assert lane_fit.packet_check(MACRO, liq)['ok']


def test_draft_lane_check_needs_a_tie_in_for_broad_news(monkeypatch):
    assert not lane_fit.draft_check(SOLBASE, 'Pivoting to a stablecoin model swaps the Bitcoin mandate for state risk')['ok']
    assert lane_fit.draft_check(PERP, 'Bitcoin dumped and $487M of longs got liquidated; funding is still positive.')['ok']
    assert lane_fit.draft_check(SOLBASE, 'Bitcoin dipped but Solana app revenue kept climbing.')['ok']
    monkeypatch.setenv('FD_LANE_FIT', '0')
    assert lane_fit.draft_check(SOLBASE, 'Bitcoin ETF flows')['ok']


def test_lane_gate_drops_off_lane_packets_and_logs_them():
    dc = _script('daily_compose')

    def g(i, title, handle=None):
        return [{'unit_id': f'u{i}', 'source': {'id': f's{i}', 'title': title, 'adapter': f'x:{handle}' if handle else 'rss',
                                                'url': f'https://x.com/{handle}/status/{i}' if handle else ''},
                 'unit': {'statement': title, 'numbers': []}}]
    pools = {'crypto_perp_dex_en': [g(1, 'Funding flips negative on Hyperliquid'), g(2, 'Robinhood buys $25M of bitcoin')],
             'crypto_macro_en': [g(3, 'Robinhood buys $25M of bitcoin')]}
    info = {}
    dc.lane_gate(pools, [PERP, MACRO], {'crypto_perp_dex_en': [], 'crypto_macro_en': []}, info)
    assert [x[0]['source']['id'] for x in pools['crypto_perp_dex_en']] == ['s1']
    assert len(pools['crypto_macro_en']) == 1
    assert info['off_lane_rejects']['crypto_perp_dex_en']['rejected'] == 1


def test_inbox_row_holds_off_lane_drafts():
    dc = _script('daily_compose')
    pick = {'source_id': 's1', 'post_format': {'type': 'quick_take'}, 'suggested_post_time_london': REF.isoformat(),
            'angle_why': 'x', 'shared_event_with': [], 'same_language': True}
    result = {'id': 'compose-x', 'plan': pick, 'body': 'b', 'text': 'b', 'draft_status': 'draft_ready', 'status': 'held',
              'lane_fit': {'ok': False, 'detail': 'broad macro / BTC / ETF draft without a crypto_ecosystem_sol_base tie-in'}}
    row = dc.inbox_row(result, {'id': 'sol_base_alpha_en', 'no': 31, 'name': 'n', 'beat': 'b', 'lang': 'en'},
                       date(2026, 10, 9), 'run1')
    assert row['held'] and row['hold_reason'].startswith('off_lane')


# ------------------------------------------------------------------ 3. hook + voice

def test_codes_are_classified(hook_on):
    out = {f['code']: f['level'] for f in qa_levels.classify(
        [{'code': c, 'detail': ''} for c in ('weak_hook', 'unattributed_forecast', 'stale_market_claim')], frame_found=True)}
    assert out == {'weak_hook': 'soft', 'unattributed_forecast': 'hard', 'stale_market_claim': 'hard'}
    assert 'weak_hook' in hv.REPAIR_TRIGGER and qa_levels.FIXES['unattributed_forecast']


def test_weak_hook(hook_on):
    assert hv.hook_findings('最近市场又开始躁动了。\n第二行', 'zh')
    assert hv.hook_findings("Let's talk about the market today.", 'en')
    assert hv.hook_findings('It is naive to view this as a mere payment upgrade.', 'en')
    assert not hv.hook_findings('单日爆掉 4.87 亿美元多单。', 'zh')
    assert not hv.hook_findings('我今天把资金费率表又翻了一遍。', 'zh')
    assert not hv.hook_findings('Tether froze $2.76M of a Brazilian firm.', 'en')
    assert not hv.hook_findings("I've logged funding on Hyperliquid every morning this week.", 'en')
    assert not hv.hook_findings('传统大行现在加速拥抱加密机构，富国银行已经和Kraken开谈。', 'zh')


BFE = ('年底冲上10万美元真的只是画饼？借着资金和政策利好其实大有希望！\n\n这波拉升根本没在炒宏观贬值的冷饭。\n\n'
       '既然价格已经实打实创下近期新高，还在观望的资金还能憋多久？')
UNITS = [{'statement': 'Standard Chartered expects bitcoin to reach $100,000 by year-end', 'speaker': 'Standard Chartered',
          'published_at': '2026-10-02T13:34:40+00:00'}]
SRC = {'publisher': 'The Block', 'published_at': '2026-10-02T13:34:40+00:00', 'title': 'Bitcoin nears highest level'}


def test_source_forecast_as_own_view_is_flagged_and_credited_one_passes(hook_on):
    assert [f['code'] for f in hv.forecast_findings(BFE, UNITS, SRC, 'zh')] == ['unattributed_forecast']
    assert not hv.forecast_findings('渣打认为比特币年底有望冲上10万美元，我不太买账。', UNITS, SRC, 'zh')
    assert not hv.forecast_findings('Standard Chartered expects $100,000 by year-end; I am not buying it.', UNITS, SRC, 'en')
    assert hv.forecast_findings('Bitcoin will hit $100,000 by year-end.', UNITS, SRC, 'en')
    # a number the source never gave is not a source forecast (other checks own it)
    assert not hv.forecast_findings('Bitcoin will hit $150,000 by year-end.', UNITS, SRC, 'en')


def test_stale_new_high_by_age_and_by_price(hook_on, monkeypatch):
    now = datetime(2026, 10, 8, 6, 26, tzinfo=timezone.utc)
    assert [f['code'] for f in hv.stale_claim_findings(BFE, UNITS, SRC, now)] == ['stale_market_claim']
    fresh = {'published_at': '2026-10-08T01:00:00+00:00'}
    monkeypatch.setattr(hv, '_PRICE_CACHE', {})
    rows_down = [(0, 0, 126000, 0, 125000, 0)] * 10 + [(0, 0, 84000, 0, 83500, 0)]
    out = hv.stale_claim_findings('BTC just printed a new high.', [], fresh, now, fetch=lambda s: {'rows': rows_down})
    assert out and 'under its recent high' in out[0]['detail']
    monkeypatch.setattr(hv, '_PRICE_CACHE', {})
    rows_up = [(0, 0, 120000, 0, 119000, 0)] * 10 + [(0, 0, 126000, 0, 125900, 0)]
    assert not hv.stale_claim_findings('BTC just printed a new high.', [], fresh, now, fetch=lambda s: {'rows': rows_up})
    assert not hv.stale_claim_findings('BTC drifted sideways.', UNITS, SRC, now)


def test_hook_voice_off_switch(monkeypatch):
    monkeypatch.setenv('FD_HOOK_VOICE', '0')
    assert hv.findings(BFE, UNITS, SRC, None, 'zh') == []


def test_prompt_rule_mentions_the_three_rules():
    rule = hv.PROMPT_RULE
    assert 'Line 1' in rule and 'attribute' in rule and 'new high' in rule and 'first person' in rule


# ------------------------------------------------------------------ 4. media priority + cold start

def test_cold_start_window(monkeypatch):
    cfg = {'window_days': 14, 'default_first_day': '2026-10-08', 'first_day': {'new_acct': None}}
    assert cold_start.is_cold('old_acct', date(2026, 10, 9), cfg)
    assert not cold_start.is_cold('old_acct', date(2026, 10, 22), cfg)
    assert cold_start.is_cold('new_acct', date(2026, 12, 1), cfg)
    monkeypatch.setenv('FD_COLD_START', '0')
    assert not cold_start.is_cold('new_acct', date(2026, 10, 9), cfg)


def test_hot_quote_target():
    src = {'url': 'https://x.com/donor/status/123', 'published_at': (REF - timedelta(hours=3)).isoformat()}
    assert cold_start.hot_quote_target(src, REF)
    assert not cold_start.hot_quote_target(dict(src, published_at=(REF - timedelta(hours=30)).isoformat()), REF)
    assert not cold_start.hot_quote_target(src, REF, own_handles=['@donor'])
    assert not cold_start.hot_quote_target(dict(src, x_metrics={'likes': 2, 'views': 100}), REF)
    assert cold_start.hot_quote_target(dict(src, x_metrics={'likes': 50}), REF)
    assert not cold_start.hot_quote_target({'url': 'https://example.com/a', 'published_at': src['published_at']}, REF)


def test_cold_start_quote_floor_in_post_mode(monkeypatch, tmp_path):
    monkeypatch.setenv('FD_ENGAGE', '0')   # the legacy 60% floor; live/engagement.py replaces it (test_engagement_oct8)
    src = {'url': 'https://x.com/donor/status/1', 'published_at': (REF - timedelta(hours=2)).isoformat()}
    rows = [{'id': f'd{i}', 'account_id': 'crypto_meme_en', 'day': '2026-10-09', 'source': src,
             'suggested_post_time_london': REF.isoformat(), 'post_format': {'type': 'quick_take'}} for i in range(200)]
    quotes = sum(post_mode.decide(r, habits_dir=tmp_path)['post_mode'] == 'quote' for r in rows)   # no card: share 0
    assert 0.5 * 200 <= quotes <= 0.7 * 200
    monkeypatch.setenv('FD_COLD_START', '0')
    assert sum(post_mode.decide(r, habits_dir=tmp_path)['post_mode'] == 'quote' for r in rows) == 0


def test_force_quote_is_deterministic_and_about_the_share(monkeypatch):
    monkeypatch.setenv('FD_ENGAGE', '0')   # legacy path; with FD_ENGAGE on live/engagement.py decides (always False here)
    src = {'url': 'https://x.com/donor/status/1', 'published_at': (REF - timedelta(hours=2)).isoformat()}
    picks = [cold_start.force_quote('crypto_meme_en', date(2026, 10, 9), src, REF, key=f's{i}') for i in range(300)]
    assert picks == [cold_start.force_quote('crypto_meme_en', date(2026, 10, 9), src, REF, key=f's{i}') for i in range(300)]
    assert 0.5 <= sum(picks) / 300 <= 0.7


def test_media_boost_only_for_image_heavy_donors(monkeypatch):
    monkeypatch.setattr(cold_start, '_PROFILES', {'heavy': {'image_rate': 0.62}, 'light': {'image_rate': 0.2}})
    assert cold_start.boosted_p_image('heavy', 0.34) == pytest.approx(0.544)
    assert cold_start.boosted_p_image('heavy', 0.5) == 0.62
    assert cold_start.boosted_p_image('light', 0.12) == 0.12
    monkeypatch.setenv('FD_MEDIA_PRIORITY', '0')
    assert cold_start.boosted_p_image('heavy', 0.34) == 0.34


def test_pick_prefs_rank_quote_targets_and_chartable_packets(monkeypatch):
    dc = _script('daily_compose')
    monkeypatch.setattr(cold_start, '_PROFILES', {'acct': {'image_rate': 0.6}})
    hot = [{'source': {'url': 'https://x.com/d/status/9', 'published_at': (REF - timedelta(hours=1)).isoformat(),
                       'title': 'BTC funding flips'}, 'unit': {'statement': 'BTC funding flips', 'numbers': []}}]
    cold = [{'source': {'url': '', 'published_at': REF.isoformat(), 'title': 'a quiet note'},
             'unit': {'statement': 'a quiet note', 'numbers': []}}]
    k = dc.pick_prefs('acct', date(2026, 10, 9), REF)
    assert k(hot) < k(cold)


# ------------------------------------------------------------------ compose integration (scripted model)

def test_compose_weak_hook_gets_one_rewrite_and_payload_rule(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / 'tests'))
    import test_zhfix_oct6_v11 as T
    monkeypatch.setenv('FD_HOOK_VOICE', '1')
    T._iso(monkeypatch, tmp_path)
    generic = ('Interesting times for the Fed this month.\n'
               'That is because payrolls rose only 29,000 against 84,000 expected.\n'
               'October hike odds fell to 22% from 66%.')
    fake = T.EnFake([generic, generic, T.EN_FACT, T.EN_FACT])
    result = T._compose_en(fake, 'crypto_macro_en', shape='thesis_mechanism')
    assert all(p.get('hook_voice') == hv.PROMPT_RULE for p in fake.payloads['compose'])
    hr = result['hard_repair']
    assert 'weak_hook' in {f['code'] for f in hr['first_findings']} and hr['kept'] == 'retry'
    assert result['body'] == T.EN_FACT and result['draft_status'] == 'draft_ready'
    assert not [f for f in result['post_checks'] if f['code'] == 'weak_hook']


def test_compose_stubborn_weak_hook_is_never_a_hold(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / 'tests'))
    import test_zhfix_oct6_v11 as T
    monkeypatch.setenv('FD_HOOK_VOICE', '1')
    T._iso(monkeypatch, tmp_path)
    generic = ('Interesting times for the Fed this month.\n'
               'That is because payrolls rose only 29,000 against 84,000 expected.\n'
               'October hike odds fell to 22% from 66%.')
    result = T._compose_en(T.EnFake([generic]), 'crypto_macro_en', shape='thesis_mechanism')
    flags = [f for f in result['post_checks'] if f['code'] == 'weak_hook']
    assert flags and all(f['level'] == 'soft' for f in flags) and result['draft_status'] == 'draft_ready'
