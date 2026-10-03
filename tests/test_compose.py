"""P0-4e: COMPOSE + post-level checks + dispatch.

Offline, FakeClient outputs. A composed post: length inside the post_type
range, attribution frame present (attached by code), template-phrase
blacklist hits = 0, every number in the body exists in the chosen units with
a consistent metric, claim_ledger maps to units/spans, persona id+version
recorded, never publishable while the persona voice is a draft (D2).
Morris stays on the aphorism_translation chain.
"""
import json
import os
import unittest
from unittest.mock import patch

from live import compose, registry
from live.distillation import ContractError

TEXT = ('Micron revenue rose 4.8x to $54.23 billion in the quarter.\n\n'
        'Operating margin was 69.5% as memory prices kept rising.\n\n'
        'Memory makers will not build a glut because building a fab takes years and prices keep rising.')
SOURCE = {'id': 'source-x', 'source_id': 'nextplatform', 'source_hash': 'h' * 64, 'original_text': TEXT,
          'author_name': 'The Next Platform', 'title': 'Micron', 'published_at': '2026-10-02T00:00:00Z',
          'source_language': 'en', 'source_version': 'v1'}
UNITS = {'units': [
    {'kind': 'fact', 'statement': 'Revenue 4.8x to $54.23B.',
     'source_spans': [{'paragraph_id': 'P1', 'exact_text': 'Micron revenue rose 4.8x to $54.23 billion in the quarter.'}],
     'numbers': [{'text': '$54.23 billion', 'metric': 'revenue', 'period': 'quarter', 'span_ref': 0},
                 {'text': '4.8x', 'metric': 'revenue growth', 'period': 'quarter', 'span_ref': 0}],
     'speaker': 'Micron', 'speaker_type': 'company_exec', 'freshness_class': 'current'},
    {'kind': 'fact', 'statement': 'Operating margin 69.5%.',
     'source_spans': [{'paragraph_id': 'P2', 'exact_text': 'Operating margin was 69.5%'}],
     'numbers': [{'text': '69.5%', 'metric': 'operating margin', 'period': 'quarter', 'span_ref': 0}],
     'speaker': 'Micron', 'speaker_type': 'company_exec', 'freshness_class': 'current'},
    {'kind': 'mechanism', 'statement': 'Fab lead times stop a glut.',
     'source_spans': [{'paragraph_id': 'P3', 'exact_text': 'Memory makers will not build a glut because building a fab takes years and prices keep rising.'}],
     'numbers': [], 'speaker': 'The Next Platform', 'speaker_type': 'media', 'freshness_class': 'evergreen'}]}

GOOD_BODY = ('美光这个季度的营收同比增长4.8倍，达到542.3亿美元，营业利润率为69.5%。'
             '存储厂商没有扩产的冲动：建一座晶圆厂要好几年，而价格还在上涨，谁先扩产谁就先把价格打下来。'
             '这意味着供给端的克制会延续，短期内很难看到过剩。对下游买家来说，这一轮涨价不会很快结束，'
             '采购节奏和库存策略都要按更长的紧缺期来安排，而不是等着价格自己回落。'
             '换句话说，决定这轮周期长度的不是需求，而是厂商愿意让供给紧到什么程度。')


class Fake:
    def __init__(self, body=GOOD_BODY, ledger=None, units=UNITS):
        self.body, self.ledger, self.units, self.calls = body, ledger, units, []

    def __call__(self, stage, messages, max_tokens):
        self.calls.append(stage)
        if stage == 'extract':
            return {'text': json.dumps(self.units), 'finish_reason': 'stop', 'model': 'fake'}
        payload = json.loads(messages[-1]['content'])
        ids = [u['unit_id'] for u in payload['units']]
        ledger = self.ledger if self.ledger is not None else [
            {'claim': '营收与利润率', 'unit_id': ids[0], 'span_ref': 0}]
        return {'text': json.dumps({'body': self.body, 'claim_ledger': ledger}, ensure_ascii=False),
                'finish_reason': 'stop', 'model': 'fake'}


def run(fake=None, post_type=None, account='zh_industry'):
    fake = fake or Fake()
    return compose.compose_source(SOURCE, account, fake, post_type=post_type), fake


def codes(result):
    return {f['code'] for f in result['post_checks']}


class ComposeTests(unittest.TestCase):
    def test_good_post_passes_all_post_checks(self):
        result, fake = run(post_type='data_take')
        self.assertEqual(fake.calls, ['extract', 'compose'])
        self.assertEqual(result['post_checks'], [])
        self.assertEqual(result['post_type'], 'data_take')
        frame = result['attribution_frame']
        self.assertEqual(frame['text'], 'The Next Platform：')
        self.assertTrue(result['text'].startswith(frame['text']))
        lo, hi = 150, 400
        self.assertTrue(lo <= result['length'] <= hi)
        self.assertEqual(result['persona'], {'persona_id': 'zh_industry', 'version': '1'})
        self.assertFalse(result['publishable'])
        self.assertEqual(result['draft_status'], 'draft_ready')
        self.assertEqual(result['status'], 'held')
        self.assertIn('persona_voice_draft', {r['code'] for r in result['risks']})
        self.assertTrue(all(c['unit_id'] in {u['unit_id'] for u in result['units']} for c in result['claim_ledger']))

    def test_length_out_of_range(self):
        result, _ = run(Fake(body='美光营收增长4.8倍。'), post_type='data_take')
        self.assertIn('length_out_of_range', codes(result))
        self.assertEqual(result['draft_status'], 'needs_review')

    def test_blacklist_hit(self):
        result, _ = run(Fake(body='值得注意的是，' + GOOD_BODY), post_type='data_take')
        self.assertIn('template_phrase', codes(result))

    def test_number_not_in_units(self):
        result, _ = run(Fake(body=GOOD_BODY.replace('69.5%', '72%')), post_type='data_take')
        self.assertIn('number_not_in_units', codes(result))

    def test_converted_units_are_the_same_number(self):
        result, _ = run(post_type='data_take')  # 542.3亿美元 == $54.23 billion
        self.assertNotIn('number_not_in_units', codes(result))

    def test_number_bound_to_wrong_metric(self):
        body = GOOD_BODY.replace('营业利润率为69.5%', '营收占比69.5%').replace('营收同比增长4.8倍', '利润率同比增长4.8倍')
        result, _ = run(Fake(body=body), post_type='data_take')
        self.assertIn('number_metric_binding', codes(result))

    def test_source_named_in_body(self):
        result, _ = run(Fake(body=GOOD_BODY + '来源：The Next Platform'), post_type='data_take')
        self.assertIn('provenance_in_body', codes(result))

    def test_first_person_is_identity_finding(self):
        result, _ = run(Fake(body='我一直在跟踪美光。' + GOOD_BODY), post_type='data_take')
        self.assertIn('author_identity', codes(result))

    def test_claim_ledger_must_map_to_units(self):
        with self.assertRaises(ContractError):
            run(Fake(ledger=[{'claim': 'x', 'unit_id': 'cu-missing', 'span_ref': 0}]), post_type='data_take')
        with self.assertRaises(ContractError):
            run(Fake(ledger=[]), post_type='data_take')

    def test_post_type_choice_follows_units_and_persona(self):
        result, _ = run()
        self.assertIn(result['post_type'], registry.persona_for_account('zh_industry').post_type_mix)
        self.assertIn(result['post_type'], registry.post_types_for_tier('B'))

    def test_no_eligible_units_is_no_post_without_compose_call(self):
        result, fake = run(Fake(units={'units': []}))
        self.assertEqual(fake.calls, ['extract'])
        self.assertEqual(result['draft_status'], 'not_suitable')

    def test_morris_is_not_composed(self):
        with self.assertRaises(ValueError):
            run(account='en_morris_archive')


class DispatchTests(unittest.TestCase):
    def test_compose_dispatch_is_opt_in(self):
        from live.account_source_adaptation import uses_compose
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ACCOUNT_COMPOSE_PIPELINE', None)
            self.assertFalse(uses_compose('zh_industry'))
        with patch.dict(os.environ, {'ACCOUNT_COMPOSE_PIPELINE': '1'}):
            self.assertTrue(uses_compose('zh_industry'))
            self.assertFalse(uses_compose('en_morris_archive'))

    def test_adapt_source_dispatches_composed_accounts_when_enabled(self):
        import tempfile
        from pathlib import Path
        from live.account_source_adaptation import adapt_source
        fake = Fake()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ACCOUNT_COMPOSE_PIPELINE': '1'}):
            result = adapt_source(SOURCE, 'zh_industry', Path(tmp), fake)
            self.assertTrue(Path(result['result_path']).exists())
        self.assertEqual(fake.calls, ['extract', 'compose'])
        self.assertEqual(result['pipeline_version'], compose.VERSION)
        self.assertEqual(result['status'], 'held')
        self.assertEqual(result['human_review'], {'status': 'pending'})
        self.assertFalse(result['publishable'])
        self.assertEqual(result['final_draft'], result['compose']['text'])

    def test_adapt_source_compose_contract_error_is_blocked_not_raised(self):
        import tempfile
        from pathlib import Path
        from live.account_source_adaptation import adapt_source
        fake = Fake(ledger=[{'claim': 'x', 'unit_id': 'cu-missing', 'span_ref': 0}])
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ACCOUNT_COMPOSE_PIPELINE': '1'}):
            result = adapt_source(SOURCE, 'zh_industry', Path(tmp), fake)
        self.assertEqual(result['draft_status'], 'blocked')
        self.assertEqual(result['execution_failure']['code'], 'source_contract')
        self.assertEqual(result['execution_failure']['stage'], 'compose')


if __name__ == '__main__':
    unittest.main()
