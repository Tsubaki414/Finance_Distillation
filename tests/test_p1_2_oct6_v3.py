"""Oct 6 v3: soft arbitration default (P1-2), ZH own-source selection, generic credit, emotion tiers."""
import json

import pytest

from live import compose, compose_batch, emotion_contract as ec, qa_levels
from scripts import demo_matrix_compose as demo


# ---------- P1-2: soft arbitration on by default, env/explicit off ----------

def _draft(account, view, source_id='s1'):
    return {'account_id': account, 'key': account, 'status': 'held', 'draft_status': 'draft_ready',
            'source': {'id': source_id, 'source_id': source_id, 'title': 'T', 'published_at': '2026-10-06'},
            'stance': {'decision': 'adapt', 'account_view': view,
                       'view': {'subject': 'Federal Reserve policy rate', 'direction': 'higher'}},
            'units': [{'unit_id': 'u1', 'kind': 'view'}], 'post_checks': []}


def test_arbitration_mode_resolution(monkeypatch):
    monkeypatch.delenv(compose.ARBITRATION_ENV, raising=False)
    assert compose.arbitration_mode(None) == 'soft'
    monkeypatch.setenv(compose.ARBITRATION_ENV, 'off')
    assert compose.arbitration_mode(None) == 'off'
    assert compose.arbitration_mode('soft') == 'soft'           # explicit beats env
    for value in ('0', 'false', 'NO', 'none'):
        monkeypatch.setenv(compose.ARBITRATION_ENV, value)
        assert compose.arbitration_mode(None) == 'off'
    monkeypatch.setenv(compose.ARBITRATION_ENV, 'hard-block')
    with pytest.raises(ValueError):
        compose.arbitration_mode(None)


def test_arbitrate_batch_default_soft_holds_duplicate(monkeypatch):
    monkeypatch.delenv(compose.ARBITRATION_ENV, raising=False)
    out = compose.arbitrate_batch([_draft('zh_macro', 'Fed hikes again in December'),
                                   _draft('en_macro', 'Fed hikes again in December')])
    assert sorted(r['arbitration']['status'] for r in out) == ['HOLD', 'WRITE']
    held = next(r for r in out if r['arbitration']['status'] == 'HOLD')
    from live.claim_arbitration import REASON_CODE_SOFT
    assert held['stance']['account_view']                      # soft: draft kept, never deleted
    assert [f['code'] for f in held['post_checks']] == [REASON_CODE_SOFT]


def test_arbitrate_batch_off_via_env_leaves_drafts(monkeypatch):
    monkeypatch.setenv(compose.ARBITRATION_ENV, 'off')
    rows = [_draft('zh_macro', 'same'), _draft('en_macro', 'same')]
    out = compose.arbitrate_batch(rows)
    assert [r['arbitration'] for r in out] == [{'status': 'OFF', 'mode': 'off'}] * 2
    assert all(r['post_checks'] == [] for r in out)


def test_compose_batch_runs_arbitration_and_keeps_error_rows(monkeypatch):
    monkeypatch.delenv(compose.ARBITRATION_ENV, raising=False)

    def fake_compose(source, account, client, **kwargs):
        if account == 'en_industry':
            raise RuntimeError('relay down')
        return _draft(account, 'Fed hikes again in December')

    monkeypatch.setattr(compose, 'compose_source', fake_compose)
    jobs = [{'source': {'id': s}, 'account_id': a} for s, a in (('s1', 'zh_macro'), ('s1', 'en_macro'), ('s2', 'en_industry'))]
    out = compose_batch.compose_batch(jobs, client=object())
    by = {r['account_id']: r for r in out}
    assert by['en_industry']['status'] == 'error'
    assert sorted(by[a]['arbitration']['status'] for a in ('zh_macro', 'en_macro')) == ['HOLD', 'WRITE']
    off = compose_batch.compose_batch(jobs[:2], client=object(), arbitration='off')
    assert {r['arbitration']['status'] for r in off} == {'OFF'}


# ---------- ZH own-source selection ----------

def _rec(account, source, kind, uid=None, lang='en', title='T'):
    return {'unit_id': uid or f'{account}-{source}-{kind}', 'licence_tier': 'A',
            'source': {'source_hash': source, 'id': source, 'source_language': lang, 'title': title},
            'unit': {'kind': kind}}


def _pools(monkeypatch, pools):
    monkeypatch.setattr(demo, 'has_valid_view', lambda unit: unit.get('kind') == 'view')
    monkeypatch.setattr(demo, 'units_for_persona', lambda store, account, **_k: pools.get(account, []))


def test_zh_prefers_own_native_source_over_shared(monkeypatch):
    shared = [_rec('x', 'jpm', 'view', 'v-jpm'), _rec('x', 'jpm', 'fact', 'f-jpm')]
    _pools(monkeypatch, {
        'en_macro': shared,
        'zh_macro': shared + [_rec('zh', 'other_en', 'view'), _rec('zh', 'other_en', 'fact'),
                              _rec('zh', 'stats', 'view', lang='zh', title='9月PMI'),
                              _rec('zh', 'stats', 'fact', lang='zh', title='9月PMI')],
    })
    sel = {}
    chosen = demo.select_groups(object(), ['zh_macro', 'en_macro'], sel)
    assert {r['source']['id'] for r in chosen['en_macro']} == {'jpm'}
    assert {r['source']['id'] for r in chosen['zh_macro']} == {'stats'}
    assert sel['zh_macro']['mode'] == 'own_zh_native' and sel['en_macro']['mode'] == 'own'


def test_zh_shares_only_with_differentiated_angle(monkeypatch):
    en = [_rec('x', 'jpm', 'view', 'v1'), _rec('x', 'jpm', 'fact', 'f1')]
    _pools(monkeypatch, {'en_macro': en,
                         'zh_macro': en + [_rec('x', 'jpm', 'view', 'v2')]})
    sel = {}
    chosen = demo.select_groups(object(), ['zh_macro', 'en_macro'], sel)
    assert sel['zh_macro']['mode'] == 'shared_differentiated'
    assert sel['zh_macro']['dropped_view_ids'] == ['v1']
    assert {r['unit_id'] for r in chosen['zh_macro']} == {'f1', 'v2'}
    assert demo.balanced(chosen['zh_macro'])


def test_same_angle_share_is_marked_and_arbitration_still_holds(monkeypatch):
    monkeypatch.delenv(compose.ARBITRATION_ENV, raising=False)
    en = [_rec('x', 'jpm', 'view', 'v1'), _rec('x', 'jpm', 'fact', 'f1')]
    _pools(monkeypatch, {'en_macro': en, 'zh_macro': list(en)})
    sel = {}
    chosen = demo.select_groups(object(), ['zh_macro', 'en_macro'], sel)
    assert sel['zh_macro']['mode'] == 'shared_same_angle'
    assert chosen['zh_macro'] == en
    out = compose.arbitrate_batch([_draft('zh_macro', '联储12月再加息', 'jpm'),
                                   _draft('en_macro', 'Fed hikes again in December', 'jpm')])
    assert {r['account_id']: r['arbitration']['status'] for r in out}['zh_macro'] == 'HOLD'


def test_zh_without_any_balanced_packet_is_empty(monkeypatch):
    _pools(monkeypatch, {'en_industry': [_rec('x', 'a', 'view'), _rec('x', 'a', 'fact')],
                         'zh_industry': [_rec('x', 'b', 'fact')]})
    sel = {}
    chosen = demo.select_groups(object(), ['zh_industry', 'en_industry'], sel)
    assert chosen['zh_industry'] == [] and sel['zh_industry']['mode'] == 'none'


# ---------- generic credit in body ----------

@pytest.mark.parametrize('body', [
    '券商研报已将加息节点推迟至12月，我不买账。',
    '某投行认为美光的定价权还能撑两个季度。',
    'Sell-side research now has December as the last hike.',
    'A big bank thinks December is the final hike.',
    'Analysts say the cycle is done.',
])
def test_generic_credit_soft_finding(body):
    found = compose.generic_credit_findings(body, 'judgment_take')
    assert [f['code'] for f in found] == ['generic_credit_in_body']
    assert 'generic_credit_in_body' in qa_levels.SOFT and 'generic_credit_in_body' in qa_levels.FIXES


def test_generic_credit_not_flagged_for_own_voice_or_contrarian():
    assert compose.generic_credit_findings('December is the last hike, and one soft print does not change that.',
                                           'judgment_take') == []
    assert compose.generic_credit_findings('联储12月之后大概率停手。', 'judgment_take') == []
    assert compose.generic_credit_findings('Sell-side research is too early here.', 'contrarian_take') == []
    assert compose.generic_credit_findings('Analysts say the cycle is done.', 'data_take') == []


def test_compose_prompt_has_attribution_and_register_rules():
    assert '券商研报 / 某投行' in compose.COMPOSE and '"a big bank"' in compose.COMPOSE
    assert "an adopted view is the account's own call" in compose.COMPOSE
    assert 'emotion_brief.required_effect' in compose.COMPOSE
    from live import stance
    assert 'never name or\n  credit the source in account_view' in stance.STANCE


# ---------- emotion tiers (root cause) ----------

WARY_MACRO = [{'unit_id': '1', 'statement': 'Risk remains; we stay cautious and watch the downside risk carefully.',
               'source_spans': [], 'numbers': []}]


def test_low_tier_target_stays_at_floor_on_wary_finance_source():
    brief = ec.build_emotion_brief(WARY_MACRO, {'account_view': 'December is the last hike.'},
                                   lang='en', account_id='en_macro')
    assert brief['tier'] == 'low' and brief['target_intensity'] == 2
    assert 'Restrained' in brief['required_effect']


def test_low_committed_call_not_flagged_but_calm_recap_is():
    brief = ec.build_emotion_brief(WARY_MACRO, {'account_view': 'x'}, lang='en', account_id='en_macro')
    call = 'One soft payroll print does not make December the last hike. October data decides it.'
    recap = 'September payrolls rose 29k. Unemployment was 4.18% in the month.'
    assert ec.emotion_findings(call, brief) == []
    assert [f['code'] for f in ec.emotion_findings(recap, brief)] == ['emotion_drop']


def test_zh_doubt_vocabulary_detected():
    assert ec.first_two_have_reaction('对美光的定价权我深表怀疑。数据只说明了一个季度。')
    assert ec.first_two_have_reaction('这个降息预期，我打个问号。')


def test_required_effect_differs_by_tier():
    mid = ec.build_emotion_brief(WARY_MACRO, {'account_view': 'x'}, lang='zh', account_id='zh_macro')
    high = ec.build_emotion_brief(WARY_MACRO, {'account_view': 'x'}, lang='en', account_id='trading_shortterm')
    assert 'thesis_lock call carrying one clear reaction' in mid['required_effect']
    assert 'WITH the dominant emotion' in high['required_effect']
    assert high['target_intensity'] > mid['target_intensity'] >= 2


def test_adverbed_opinion_marker_is_own_view_not_identity():
    """v3 en_macro: 'I do think they pause here' is the persona's own call (Fiona: judgments as own)."""
    from live import attribution_frame as af
    assert not af.FIRST_PERSON.search(af.OPINION_MARKERS.sub(' ', 'I do think they pause here.'))
    assert not af.FIRST_PERSON.search(af.OPINION_MARKERS.sub(' ', "I don't think December is the last hike."))
    assert af.FIRST_PERSON.search(af.OPINION_MARKERS.sub(' ', 'I do hold the long end.'))
