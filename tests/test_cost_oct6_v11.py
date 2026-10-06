"""Oct 6 v11 cost: ZH scrub hits go to the small account_view rewrite (no second full stance call);
ZH stance has its own cost estimate in the slot budget. Fakes only - no model calls."""
import json

import pytest

from live import registry, stance
from scripts import demo_matrix_compose as demo

UNIT = {
    'unit_id': 'v', 'kind': 'view', 'statement': 'Supply tight.',
    'source_spans': [{'exact_text': 'Micron revenue rose'}], 'numbers': [],
    'speaker': 'S', 'speaker_type': 'media',
    'freshness_class': 'current', 'published_at': '2026-10-05T00:00:00Z',
}


def _unit():
    from tests.test_judgment import VIEW
    return dict(UNIT, view=dict(VIEW))


def _client(first_view, rewrite_view, seen):
    """Counts calls by kind: full stance (max_tokens >= 2000) vs small rewrite (400)."""
    def client(stage, messages, max_tokens):
        payload = json.loads(messages[-1]['content'])
        if payload.get('problems') is not None:
            seen.append(('rewrite', max_tokens, payload['problems']))
            return {'text': json.dumps({'account_view': rewrite_view}), 'finish_reason': 'stop'}
        seen.append(('stance', max_tokens, bool(payload.get('rewrite_note'))))
        av = rewrite_view if payload.get('rewrite_note') else first_view
        return {'text': json.dumps({'decision': 'take', 'account_view': av, 'supporting_unit_ids': ['v'],
                                    'rationale': 'Supply.', 'confidence': 0.7}), 'finish_reason': 'stop'}
    return client


def test_zh_scrub_hits_route_to_small_rewrite_without_second_stance():
    seen = []
    client = _client('才是关键', '定价权撑不过新一轮扩产就会破。', seen)
    out = stance.stance_step(_unit(), registry.persona_for_account('zh_industry'), client, sleep=lambda s: None)
    kinds = [k for k, *_ in seen]
    assert kinds == ['stance', 'rewrite']              # one full stance only
    assert not any(note for k, _, note in seen if k == 'stance')
    rewrite = [r for r in seen if r[0] == 'rewrite'][0]
    assert rewrite[1] == 400 and 'banned span: 才是关键' in rewrite[2]
    assert out['stance_scrub_retry'] == {'attempted': False, 'routed_to': 'zh_view_rewrite',
                                         'first_hits': ['才是关键']}
    assert out['stance_zh_retry']['kept'] == 'retry'
    assert out['account_view'] == '定价权撑不过新一轮扩产就会破。'


def test_zh_routed_rewrite_still_rejects_remaining_scrub_hits():
    seen = []
    client = _client('才是关键', '才是关键', seen)
    out = stance.stance_step(_unit(), registry.persona_for_account('zh_industry'), client, sleep=lambda s: None)
    assert [k for k, *_ in seen] == ['stance', 'rewrite']
    assert out['stance_zh_retry']['kept'] == 'original'
    assert out['stance_zh_retry']['reject_reason'] == 'scrub_hits'
    assert out['stance_scrub_retry']['routed_to'] == 'zh_view_rewrite'


def test_banned_spans_count_as_problems_even_without_view_findings():
    calls = []

    def client(stage, messages, max_tokens):
        calls.append(json.loads(messages[-1]['content']))
        return {'text': json.dumps({'account_view': '定价权撑不过扩产。'}), 'finish_reason': 'stop'}
    value = {'account_view': '定价权撑不过扩产才是关键。', 'view': {}}
    assert stance.zh_account_view_rewrite(client, dict(value), []) is None   # no findings, no spans: no call
    assert calls == []
    meta = stance.zh_account_view_rewrite(client, value, [], banned_spans=['才是关键'])
    assert len(calls) == 1 and meta['kept'] == 'retry' and value['account_view'] == '定价权撑不过扩产。'


def test_en_keeps_full_stance_scrub_retry():
    seen = []
    client = _client('valuation-free optimism', 'Memory pricing power breaks once new capacity lands.', seen)
    out = stance.stance_step(_unit(), registry.persona_for_account('en_macro'), client, sleep=lambda s: None)
    assert [(k, note) for k, _, note in seen] == [('stance', False), ('stance', True)]
    assert out['stance_scrub_retry']['attempted'] is True and 'routed_to' not in out['stance_scrub_retry']
    assert 'stance_zh_retry' not in out


# --- cost model ---------------------------------------------------------------------------------

def _call(root, i, cost, max_tokens, stage='stance', zh_rule=False):
    d = root / 'demo_matrix_t' / 'calls'
    d.mkdir(parents=True, exist_ok=True)
    msgs = [{'role': 'user', 'content': json.dumps({'zh_units_rule': 'x'} if zh_rule else {'unit': 1})}]
    (d / f'{stage}{i}.json').write_text(json.dumps({'stage': stage, 'status': 'completed', 'max_tokens': max_tokens,
                                                    'estimated_cost_usd': cost, 'messages': msgs}))


def test_slot_cost_model_splits_zh_and_en_stance(tmp_path):
    for i in range(10):
        _call(tmp_path, i, 0.10, 2000)                         # EN stance
        _call(tmp_path, 100 + i, 0.05, 4000, stage='compose')
        _call(tmp_path, 200 + i, 0.012, 400)                   # small rewrite: ignored
    for i in range(5):
        _call(tmp_path, 300 + i, 0.30, 3000)                   # ZH by max_tokens
    _call(tmp_path, 400, 0.31, 2000, zh_rule=True)             # ZH by zh_units_rule in the request
    m = demo.slot_cost_model(tmp_path)
    assert m['stance_usd'] == 0.10 and m['stance_zh_usd'] == 0.31 and m['compose_usd'] == 0.05
    assert 'ZH stance observed p90 of 6' in m['source']


def test_slot_cost_model_zh_default_below_five_samples(tmp_path):
    for i in range(10):
        _call(tmp_path, i, 0.10, 2000)
        _call(tmp_path, 100 + i, 0.05, 4000, stage='compose')
    for i in range(4):
        _call(tmp_path, 300 + i, 0.40, 3000)
    m = demo.slot_cost_model(tmp_path)
    assert m['stance_usd'] == 0.10 and m['stance_zh_usd'] == demo.COST_DEFAULTS['stance_zh_usd']


def test_budget_plan_sizes_zh_slots_higher():
    m = dict(demo.COST_DEFAULTS, source='test')
    en = demo.budget_plan(2.5, 4, m)
    mixed = demo.budget_plan(2.5, 4, m, langs=['zh', 'zh', 'en', 'en'])
    zh_base = round(m['stance_zh_usd'] + m['compose_usd'] + m['compose_reserve_usd'], 3)
    en_base = round(m['stance_usd'] + m['compose_usd'] + m['compose_reserve_usd'], 3)
    assert en['slot_base_usd'] == [en_base] * 4 and en['base_need_usd'] == en_base   # old signature unchanged
    assert mixed['slot_base_usd'] == [zh_base, zh_base, en_base, en_base] and zh_base > en_base
    assert mixed['total_base_need_usd'] == pytest.approx(2 * zh_base + 2 * en_base, abs=1e-3)
    assert demo.SLOT_MIN_ZH_USD == zh_base and demo.slot_min_usd('zh_macro') == zh_base
    assert demo.slot_min_usd('en_macro') == demo.SLOT_MIN_USD == en_base
    # a cap that funds 4 EN slots at base funds only 3 when two are ZH
    cap = 4 * en_base + 0.01
    assert demo.budget_plan(cap, 4, m)['slots_funded'] == 4
    assert demo.budget_plan(cap, 4, m, langs=['zh', 'zh', 'en', 'en'])['slots_funded'] == 3
    lines = '\n'.join(demo.plan_lines(mixed))
    assert f"EN ${m['stance_usd']:.3f} / ZH ${m['stance_zh_usd']:.3f}" in lines
