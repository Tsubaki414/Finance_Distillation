"""Oct 6: zh_macro named 摩根大通 (hard never_name_in_post) on a generic sell-side credit.
The compose payload must carry the never-name list + rule and hide the bank as unit speaker."""
import json

from tests.test_compose import Fake, SOURCE
from live import compose


class Spy(Fake):
    def __call__(self, stage, messages, max_tokens):
        if stage == 'compose':
            self.payload = json.loads(messages[-1]['content'])
        return super().__call__(stage, messages, max_tokens)


def test_sell_side_payload_carries_never_name_rule_and_generic_speaker():
    source = {**SOURCE, 'source_id': 'reportgem_goldman_sachs', 'adapter': 'reportgem',
              'publisher': 'Goldman Sachs'}
    spy = Spy()
    compose.compose_source(source, 'zh_industry', spy, post_type='data_take')
    rule = spy.payload['never_name']
    assert 'Goldman Sachs' in rule['names'] and '高盛' in rule['names']
    assert 'translation' in rule['rule'] and '券商研报' in rule['rule']
    assert {u['speaker'] for u in spy.payload['units']} == {'券商研报'}


def test_named_source_payload_unchanged():
    spy = Spy()
    compose.compose_source(SOURCE, 'zh_industry', spy, post_type='data_take')
    assert 'never_name' not in spy.payload
    assert 'Micron' in {u['speaker'] for u in spy.payload['units']}
