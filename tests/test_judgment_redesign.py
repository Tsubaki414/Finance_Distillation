"""Judgment redesign: pack balance, signature hard constraints, ledger continuity."""
import json

from live import compose, view_ledger
from live.stance import stance_step
from tests.test_compose import Fake, GOOD_BODY, SOURCE, UNITS, run


def _units_fact_only():
    """Two facts, no mechanism — pure data pool."""
    return {'units': [u for u in UNITS['units'] if u['kind'] == 'fact']}


def _units_with_view():
    rows = list(UNITS['units'])
    rows.append({
        'kind': 'view', 'statement': 'Memory tightness will persist into next year.',
        'source_spans': [{'paragraph_id': 'P4', 'exact_text': 'Memory makers will not build a glut'}],
        'numbers': [], 'speaker': 'The Next Platform', 'speaker_type': 'media',
        'freshness_class': 'current', 'usage': 'cite',
        'view': {'subject': 'memory supply', 'direction': 'tighter', 'conviction': 'medium',
                 'horizon': 'quarters', 'reasoning': 'fab lead times', 'trace': [0]},
    })
    return {'units': rows}


def test_balance_pack_injects_non_fact_when_available():
    pool = []
    for i, u in enumerate(UNITS['units']):
        pool.append(dict(u, unit_id=f'cu-{i}', usage='cite'))
    facts = [u for u in pool if u['kind'] == 'fact']
    bal = compose.balance_pack(facts[:2], pool)
    assert any(u['kind'] in compose.NON_FACT_KINDS for u in bal)
    meta = compose.pack_balance(bal)
    assert meta['non_fact'] >= 1 and not meta['pure_data']


def test_balance_pack_allows_pure_data_only_when_no_non_fact():
    pool = [dict(u, unit_id=f'cu-{i}', usage='cite')
            for i, u in enumerate(_units_fact_only()['units'])]
    bal = compose.balance_pack(pool[:], pool)
    assert all(u['kind'] == 'fact' for u in bal)
    assert compose.pack_balance(bal)['pure_data'] is True


def test_choose_prefers_judgment_when_view_present():
    from live import registry
    persona = registry.persona_for_account('zh_industry')
    post_types = registry.load_post_types()
    units = []
    for i, u in enumerate(_units_with_view()['units']):
        units.append(dict(u, unit_id=f'cu-{i}', usage='cite'))
    # zh_industry mix includes judgment_take or data_take — with view, choose should not prefer data_take first
    pt = compose.choose(units, persona, 'B', post_types)
    # If judgment_take is in mix and eligible, it should win over data_take
    mix = persona.post_type_mix
    if mix.get('judgment_take', 0) > 0 and compose.eligible('judgment_take', units):
        assert pt == 'judgment_take'
    else:
        assert pt is not None


def test_compose_payload_marks_signature_hard_constraints():
    class Spy(Fake):
        def __call__(self, stage, messages, max_tokens):
            self.calls.append(stage)
            if stage == 'extract':
                return {'text': json.dumps(self.units), 'finish_reason': 'stop', 'model': 'fake'}
            self.payload = json.loads(messages[-1]['content'])
            return super().__call__(stage, messages, max_tokens)

    spy = Spy()
    result, _ = run(spy, post_type='data_take', account='zh_industry')
    sig = spy.payload['persona']['signature']
    assert sig.get('hard_constraints') and any('HARD' in h for h in sig['hard_constraints'])
    assert sig.get('openings') and sig.get('closings')
    assert 'pack_balance' in result
    assert result['pack_balance']['non_fact'] >= 1  # UNITS include mechanism


def test_ignores_prior_view_soft_flag(tmp_path):
    led = view_ledger.ViewLedger('en_macro', tmp_path)
    prior = led.record(
        {'decision': 'take', 'account_view': 'One soft PCE print does not clear the bar for easing.',
         'view': {'subject': 'Federal Reserve policy', 'direction': 'neutral', 'conviction': 'medium', 'horizon': 'months'}},
        unit_ids=[], source_ids=[])
    # Fresh unrelated wording on same subject, no revises_view_id
    new = {'decision': 'take',
           'account_view': 'Rate cuts are locked in by Christmas regardless of data.',
           'view': {'subject': 'Federal Reserve policy', 'direction': 'bullish', 'conviction': 'high', 'horizon': 'months'}}
    flags = led.ignores_prior(new)
    assert flags and flags[0]['code'] == 'ignores_prior_view'
    # Continuity / revise clears it
    new2 = dict(new, revises_view_id=prior['id'])
    assert led.ignores_prior(new2) == []
    cont = {'decision': 'take',
            'account_view': 'One soft PCE print still does not clear the bar for easing into year end.',
            'view': {'subject': 'Federal Reserve policy', 'direction': 'neutral', 'conviction': 'medium', 'horizon': 'months'}}
    assert led.ignores_prior(cont) == []


def test_stance_prompt_mentions_continue_update():
    from live import stance as st
    assert 'PREFER continuing or updating' in st.STANCE
