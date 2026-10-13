"""Oct 13: EN filler-opener ban at the final opener step, selection-time story cap, depth check."""
from live import opener_mix, one_per_story, depth_check


def test_filler_opener_stripped():
    for b in ('ngl seeing USDe slip leaves me skeptical', 'TBH, the bid is thin', 'idk - flows look weak'):
        nb, ch = opener_mix.fix_opener(b, 'en')
        assert not nb.lower().startswith(('ngl', 'tbh', 'idk')) and nb[0].isupper() and ch


def test_filler_not_mid_word():
    nb, ch = opener_mix.fix_opener('Nglobal liquidity is turning', 'en')
    assert nb == 'Nglobal liquidity is turning'


def _p(url, motif=None):
    return {'url': url, 'source_id': url, 'title': url, 'story': {'keys': [motif] if motif else []}}


def test_cap_plan_cross_account():
    plan = {'a': [_p('https://x/1', 'motif:d:m1')], 'b': [_p('https://x/2', 'motif:d:m1'), _p('https://x/3')],
            'c': [_p('https://x/1')]}
    dropped = one_per_story.cap_plan(plan, ['a', 'b', 'c'], env={})
    assert [p['url'] for p in plan['a']] == ['https://x/1']
    assert [p['url'] for p in plan['b']] == ['https://x/3']
    assert plan['c'] == [] and len(dropped) == 2


def test_cap_plan_respects_ready_rows_and_switch():
    ready = [{'account_id': 'z', 'draft_status': 'draft_ready', 'source': {'url': 'https://x/1'}}]
    plan = {'a': [_p('https://x/1')]}
    one_per_story.cap_plan(plan, ['a'], ready, env={})
    assert plan['a'] == []
    plan = {'a': [_p('https://x/1')]}
    one_per_story.cap_plan(plan, ['a'], ready, env={'FD_STORY_CAP_SELECT': '0'})
    assert len(plan['a']) == 1


def test_depth():
    relay = 'Papertrade hit $80 billion in volume.\n\nUsers lost $4.73 million.'
    assert depth_check.findings(relay, 'en', env={})
    deep = relay + '\n\nWatch whether volume holds once the points program ends.'
    assert not depth_check.findings(deep, 'en', env={})
    assert not depth_check.findings('回看｜2025年10月。BTC 跌了', 'zh', env={})
    assert not depth_check.findings(relay, 'en', env={'FD_DEPTH_CHECK': '0'})
    assert depth_check.findings('美国9月CPI预计上涨3.7%。', 'zh', env={})
    assert not depth_check.findings('美国9月CPI预计上涨3.7%。接下来关注核心服务通胀。', 'zh', env={})


def test_analysis_sources_ranked_first():
    plan = {'a': [{'url': 'https://f/1', 'source_id': 'lf-chaincatcher-1', 'title': 'f'},
                  {'url': 'https://m/2', 'source_id': 'ch140_moontower', 'title': 'm'}]}
    one_per_story.cap_plan(plan, ['a'], env={})
    assert plan['a'][0]['source_id'] == 'ch140_moontower'


# ---- Oct 13 07:37: pre-draft filters + official provider with subrouter provider fallback
from live import predraft_filter as pf, stage_models

REF = '2026-10-13T01:35:00+00:00'


def _pick(**kw):
    base = {'source_id': 'x-1', 'published_at': '2026-10-12T20:00:00+00:00', 'numbers': 3, 'unit_ids': ['a', 'b'],
            'title': 'BTC ETF flows', 'suggested_post_time_london': '2026-10-13T08:00:00+01:00'}
    base.update(kw)
    return base


def test_pre_fresh():
    assert pf.reason(_pick(published_at='2026-10-10T00:00:00+00:00'), env={}).startswith('pre_fresh')
    assert pf.reason(_pick(), env={}) is None
    assert pf.reason(_pick(published_at='2026-10-10T00:00:00+00:00'), env={'FD_PRE_FRESH': '0'}) is None


def test_pre_lookback_and_facts():
    assert pf.reason(_pick(title='再看上周五推文'), env={}).startswith('pre_lookback')
    assert pf.reason(_pick(source_id='em-flash-1', numbers=0), env={}).startswith('pre_facts')
    assert pf.reason(_pick(numbers=0, unit_ids=['a']), env={}).startswith('pre_facts')
    assert pf.reason(_pick(numbers=0, unit_ids=['a', 'b', 'c']), env={}) is None   # a view post with reasoning


def test_apply_and_master_switch():
    plan = {'a': [_pick(), _pick(source_id='lf-x', numbers=0)], 'b': [_pick(published_at='2026-10-01T00:00:00Z')]}
    dropped = pf.apply(plan, env={})
    assert len(plan['a']) == 1 and plan['b'] == [] and len(dropped) == 2
    plan = {'b': [_pick(published_at='2026-10-01T00:00:00Z')]}
    assert pf.apply(plan, env={'FD_PREDRAFT': '0'}) == [] and len(plan['b']) == 1


def test_btc_tvn_count():
    row = {'draft_status': 'draft_ready', 'archive': {'variant': 'then_vs_now', 'then_vs_now': {'label': 'BTC'}}}
    assert pf.btc_tvn_today([row, {**row, 'held': True}]) == 1
    assert pf.btc_tvn_max({}) == 1 and pf.btc_tvn_max({'FD_PRE_BTC_TVN': '0'}) is None


def test_official_primary_subrouter_provider_fallback():
    t = stage_models.from_env(stage_models.load(), {'FD_GEMINI_PROVIDER': 'official', 'SUBROUTER_API_KEY': 'x'})
    for st in ('compose', 'stance', 'extract', 'extract_flash'):
        fb = stage_models.fallback(t, st)
        assert stage_models.is_gemini_native(t['stages'][st]['base_url'])
        assert fb and fb['provider_fallback'] and stage_models.is_subrouter(fb['base_url'])
        assert stage_models.model_fallback(t, st) is None
    t = stage_models.from_env(stage_models.load(), {'FD_GEMINI_PROVIDER': 'official', 'SUBROUTER_API_KEY': 'x',
                                                    'FD_OFFICIAL_SUBROUTER_FALLBACK': '0'})
    assert stage_models.fallback(t, 'compose') is None
    t = stage_models.from_env(stage_models.load(), {'FD_GEMINI_PROVIDER': 'official'})
    assert stage_models.fallback(t, 'compose') is None


# ---- Oct 13 07:56: evergreen exempt from the 48 h hold; pre-draft lane gate for evergreen picks
from live import fresh_hold


def _evg_row(**kw):
    r = {'id': 'arc-1-acct-9', 'post_kind': 'archive_lookback', 'text': '风险管理先于收益。仓位决定你能活多久。',
         'body': '风险管理先于收益。仓位决定你能活多久。', 'archive': {'variant': 'evergreen'}, 'lang': 'zh',
         'day': '2026-10-13', 'source': {'published_at': '2025-01-01T00:00:00+00:00'},
         'suggested_post_time_london': '2026-10-13T08:00:00+01:00', 'draft_status': 'draft_ready'}
    r.update(kw)
    return r


def test_evergreen_exempt_from_fresh_hold(monkeypatch):
    from live import stale_frame
    monkeypatch.setattr(stale_frame, 'findings', lambda *a, **k: [])
    hold, why, det = fresh_hold.check(_evg_row(), env={})
    assert not hold and det.get('evergreen')
    hold, why, _ = fresh_hold.check(_evg_row(), env={'FD_FRESH_EVERGREEN_EXEMPT': '0'})
    assert hold and why.startswith('stale_source')
    # then_vs_now (not evergreen) without a 回看 frame still falls through to the age check
    hold, _, _ = fresh_hold.check(_evg_row(archive={'variant': 'then_vs_now'}), env={})
    assert hold


def test_predraft_fresh_exempts_evergreen():
    p = _pick(published_at='2025-01-01T00:00:00+00:00', archive={'variant': 'evergreen'})
    assert pf.reason(p, env={}) is None


def test_evergreen_lane_gate_predraft(monkeypatch):
    from live import archive_evergreen as ae, story_dedupe, archive_lookback as al
    monkeypatch.setattr(ae, 'eligible', lambda p, a, c: ({**p, 'text': p['text'], 'rule_score': 2.0}, 'ok'))
    monkeypatch.setattr(story_dedupe, 'archive_gate', lambda *a, **k: ('off_lane -> crypto_prediction_zh', {}))
    handed = []
    monkeypatch.setattr(al, 'hand_over', lambda day, acc, p, why, v: handed.append(why))
    posts = [{'id': '1', 'handle': 'h', 'text': 'x', 'engagement': 1}]
    out = ae.candidates(posts, {'id': 'crypto_onchain_zh', 'lang': 'zh'}, '2026-10-13', config={})
    assert out == [] and handed == ['off_lane -> crypto_prediction_zh']
    monkeypatch.setenv('FD_PRE_EVERGREEN_LANE', '0')
    handed.clear()
    ae.candidates(posts, {'id': 'crypto_onchain_zh', 'lang': 'zh'}, '2026-10-13', config={})
    assert handed == []
