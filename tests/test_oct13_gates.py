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
