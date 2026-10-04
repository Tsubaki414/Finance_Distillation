"""Per-account view ledger (views only, never positions): the stance step sees related prior
calls and may combine several units; a draft contradicting an earlier call without revising it
gets a soft finding; accepted drafts record their view."""
import json

import pytest

from live import compose, view_ledger
from live.stance import stance_step
from tests.test_compose import Fake, SOURCE


def view(subject='Bitcoin', direction='bearish', account_view='Bitcoin looks fragile into year end.'):
    return {'decision': 'take', 'account_view': account_view, 'confidence': 0.7,
            'view': {'subject': subject, 'direction': direction, 'conviction': 'medium', 'horizon': 'months'}}


def test_record_and_related(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    e = led.record(view(), unit_ids=['cu-1'], source_ids=['s1'])
    assert e['id'] and e['account_id'] == 'crypto_macro_en'
    rel = led.related('Bitcoin outlook fragile', k=3)
    assert rel and rel[0]['id'] == e['id']
    assert view_ledger.ViewLedger('other', tmp_path).entries() == []      # per-account isolation


def test_positions_are_never_recorded(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    with pytest.raises(ValueError):
        led.record(view(account_view='We are long Bitcoin and added to our position.'), unit_ids=[], source_ids=[])


def test_contradiction_flagged_unless_revised(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    prior = led.record(view(), unit_ids=[], source_ids=[])
    new = view(direction='bullish', account_view='Bitcoin looks strong into year end.')
    assert [f['code'] for f in led.contradictions(new)] == ['contradicts_prior_view']
    new['revises_view_id'] = prior['id']
    assert led.contradictions(new) == []
    assert led.contradictions(view(subject='Gold', direction='bullish', account_view='Gold looks strong.')) == []


class StanceClient:
    def __init__(self, answer):
        self.answer, self.payloads = answer, []

    def __call__(self, stage, messages, max_tokens):
        self.payloads.append(json.loads(messages[-1]['content']))
        return {'text': json.dumps(self.answer), 'finish_reason': 'stop', 'model': 'fake'}


def test_stance_sees_prior_views_and_may_combine_units(tmp_path):
    from live import registry
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    led.record(view(), unit_ids=[], source_ids=[])
    unit = {'unit_id': 'cu-v', 'kind': 'view', 'statement': 'Bitcoin rally lacks ETF flow support.', 'speaker': 'Glassnode',
            'source_spans': [{'exact_text': 'Bitcoin rally lacks ETF flow support.'}], 'numbers': [],
            'view': {'subject': 'Bitcoin', 'direction': 'bearish', 'conviction': 'medium', 'horizon': 'weeks',
                     'reasoning': 'ETF flows are weak.', 'trace': [0]}}
    ctx = [{'unit_id': 'cu-f', 'kind': 'fact', 'statement': 'Spot and ETF volume is near range lows.', 'numbers': []}]
    client = StanceClient({'decision': 'take', 'account_view': 'Bitcoin rally is thin without ETF flows.',
                           'supporting_unit_ids': ['cu-v', 'cu-f'], 'rationale': 'flows plus volume', 'confidence': 0.6})
    out = stance_step(unit, registry.persona_for_account('crypto_macro_en'), client, context_units=ctx, ledger=led)
    payload = client.payloads[-1]
    assert payload['prior_views'] and payload['context_units'][0]['unit_id'] == 'cu-f'
    assert out['supporting_unit_ids'] == ['cu-v', 'cu-f']
    assert 'ledger_findings' in out


def test_compose_records_view_and_flags_flip(tmp_path):
    from tests.test_compose import UNITS, GOOD_BODY
    led = view_ledger.ViewLedger('zh_industry', tmp_path)
    stance = {'decision': 'take', 'account_view': '存储供给偏紧会延续。', 'confidence': 0.7, 'supporting_unit_ids': [],
              'view': {'subject': 'memory supply', 'direction': 'tighter', 'conviction': 'medium', 'horizon': 'quarters'}}
    r = compose.compose_source(SOURCE, 'zh_industry', Fake(), post_type='data_take', stance_output=stance, view_ledger=led)
    assert r['draft_status'] == 'draft_ready'
    flip = dict(stance, account_view='存储供给会转松。', view=dict(stance['view'], direction='wider'))
    r2 = compose.compose_source(SOURCE, 'zh_industry', Fake(), post_type='data_take', stance_output=flip, view_ledger=led)
    assert 'contradicts_prior_view' in [f['code'] for f in r2['post_checks']]
    assert len(led.entries()) == 2   # soft finding: still a draft, still recorded
