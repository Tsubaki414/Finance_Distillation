"""Control-flow/contract tests, not model quality measurements."""
import json
from pathlib import Path
import tempfile
import unittest
from live.distillation import Pipeline, comparison_rows, export
from live.editorial import EditorialPipeline, FIDELITY_CHECKS, numeric_text
from live.fidelity import numbers

SOURCE = 'The policy rate fell 25 basis points. Banks may pass the cut through.\n\nThe rate fell 25 basis points; credit demand has not recovered.'
BODY = '政策利率下调25个基点。银行可能传导这次降息，但信贷需求尚未恢复。'
ACCOUNT = [{'id': 'zh_macro', 'enabled': True, 'lang': 'zh'}]


class TestClient:
    def __init__(self, overrides=None):
        self.calls, self.overrides = [], overrides or {}

    def __call__(self, stage, messages, max_tokens):
        payload = json.loads(messages[1]['content'])
        self.calls.append((stage, payload))
        value = {
            'routing': {'decision': 'MOVE', 'worth_moving': True, 'account_id': 'zh_macro', 'reason': 'test', 'confidence': .9},
            'editorial': {'paragraph_ids': ['P1', 'P2'], 'reason': 'Complete range', 'guidance': 'Remove the repeated rate figure; keep the caution.',
                          },
            'adaptation': {'segments': [{'text': BODY, 'source_paragraph_ids': ['P1', 'P2']}], 'editor_notes': 'PRIVATE repeat removed', 'needs_source': False},
            'qa': {'checks': dict.fromkeys(FIDELITY_CHECKS, True), 'findings': [],
                   'identity_review': [], 'calculation_review': [],
                   'numeric_notes': 'Repeated 25bp figure appears once; no substantive omission.',
                   'editorial_review': 'TEST DOUBLE: does not establish editorial quality'},
            'identity_qa': {'valid': False, 'observations': [], 'findings': [
                {'severity':'fidelity','code':'personal_identity_requires_review','source_quote':'',
                 'output_quote':'','detail':'TEST DOUBLE ownership failure','repairable':False}]},
        }[stage]
        change = self.overrides.get(stage)
        if change is not None:
            value = change(value) if callable(change) else change
        return {'text': json.dumps(value, ensure_ascii=False), 'finish_reason': 'stop', 'model': 'TEST_DOUBLE'}


class EditorialContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.row = {'text': SOURCE, 'source_language': 'en', 'content_complete': True, 'author': 'Fixture Author'}

    def run_case(self, overrides=None):
        client = TestClient(overrides)
        pipe = EditorialPipeline(Path(self.tmp.name), ACCOUNT, client)
        return pipe.run(self.row, replay=False), client

    def test_original_and_judgment_reach_writer_without_a_literal_intermediate(self):
        result, client = self.run_case()
        self.assertEqual(result['draft_status'], 'draft_ready', result)
        self.assertEqual(result['pipeline_mode'],'editorial_candidate')
        self.assertEqual(result['text'], BODY)
        self.assertNotIn('PRIVATE', result['text'])
        self.assertNotIn('translation', result)
        self.assertEqual([s for s, _ in client.calls], ['routing', 'editorial', 'adaptation', 'qa'])
        payload = dict(client.calls)['adaptation']
        self.assertEqual(payload['source']['original_text'], SOURCE)
        self.assertEqual([p['exact_text'] for p in payload['selected_passages']], SOURCE.split('\n\n'))
        self.assertIn('Remove the repeated', payload['editorial_judgment']['guidance'])
        self.assertEqual(result['review_status'], 'pending')
        self.assertIsNone(result['human_review'])
        review = comparison_rows(result)
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]['source_paragraph_ids'], ['P1', 'P2'])
        self.assertEqual(review[0]['source'], SOURCE)
        self.assertEqual(review[0]['localization'], BODY)

    def test_none_and_skip_stop_all_editorial_and_writing_calls(self):
        for decision in ['NONE', 'SKIP']:
            result, client = self.run_case({'routing': lambda v: {**v, 'decision': decision,
                'account_id': None, 'worth_moving': decision == 'NONE'}})
            self.assertEqual([s for s, _ in client.calls], ['routing'])
            self.assertEqual(result['text'], '')

    def test_editorial_preference_does_not_become_fidelity_gate(self):
        def review(v):
            return {**v, 'editorial_review': 'Accurate but the pacing could be better.',
                    'findings': [{'severity': 'editorial', 'code': 'pacing', 'source_quote': '',
                                  'output_quote': BODY, 'detail': 'A subjective pacing preference.'}]}
        result, _ = self.run_case({'qa': review})
        self.assertEqual(result['draft_status'], 'draft_ready')

    def test_new_number_cannot_pass_even_if_model_claims_fidelity(self):
        def mutation(v):
            v['segments'][0]['text'] = BODY.replace('25', '50')
            return v
        result, _ = self.run_case({'adaptation': mutation})
        self.assertEqual(result['text'], '')
        self.assertIn('new_numeric_value_or_unit', [f['code'] for f in result['qa']['findings']])

    def test_calendar_translation_is_not_a_new_number(self):
        self.assertEqual(numbers(numeric_text('Sales slowed in August, after July 2024 and late September.')),
                         numbers(numeric_text('8月销售放缓，此前是2024年7月和9月下旬。')))
        self.assertEqual(numbers(numeric_text('May the recovery continue.')), {})
        self.assertNotEqual(numbers(numeric_text('Sales slowed in August.')),
                            numbers(numeric_text('9月销售放缓。')))

    def test_personal_holdings_stop_even_when_semantic_reviewer_misses_identity(self):
        def mutation(v):
            v['segments'][0]['text'] = BODY + ' 对我的持仓来说，情况不变。'
            return v
        result, _ = self.run_case({'adaptation': mutation})
        self.assertEqual(result['text'], '')
        self.assertIn('personal_identity_requires_review', [f['code'] for f in result['qa']['findings']])

    def test_missing_editorial_prose_is_not_a_fidelity_failure(self):
        def review(v):
            v.pop('editorial_review')
            return v
        result, _ = self.run_case({'qa': review})
        self.assertEqual(result['draft_status'], 'draft_ready')
        self.assertEqual(result['qa']['editorial_status'], 'missing_assessment')
        self.assertEqual(result['review_status'], 'pending')

    def test_missing_or_failed_fidelity_dimension_blocks(self):
        for key in FIDELITY_CHECKS:
            for absent in [True, False]:
                def review(v):
                    if absent: v['checks'].pop(key)
                    else: v['checks'][key] = False
                    return v
                with self.subTest(key=key, absent=absent):
                    result, _ = self.run_case({'qa': review})
                    self.assertEqual(result['text'], '')

    def test_invalid_selection_and_mapping_stop_safely(self):
        for stage, value in [('editorial', {'paragraph_ids': ['P2', 'P1']}),
                             ('editorial', {'needs_source': True}),
                             ('adaptation', {'segments': [{'text': BODY, 'source_paragraph_ids': ['P99']}]}),
                             ('adaptation', {'needs_source': True})]:
            result, _ = self.run_case({stage: lambda v: {**v, **value}})
            self.assertEqual(result['text'], '')
            export(result, Path(self.tmp.name) / 'failed-export')
            self.assertEqual((Path(self.tmp.name) / 'failed-export/body.txt').read_text(), '')

    def test_wrong_language_remains_a_hard_guard(self):
        def mutation(v):
            v['segments'][0]['text'] = SOURCE
            return v
        result, _ = self.run_case({'adaptation': mutation})
        self.assertEqual(result['text'], '')
        self.assertIn('wrong_or_uncertain_language', [f['code'] for f in result['qa']['findings']])

    def test_replay_cannot_confuse_experiment_with_minimal_pipeline(self):
        result, client = self.run_case()
        other = Pipeline(Path(self.tmp.name), ACCOUNT, client)
        self.assertIsNone(other.previous(result['source']))
        self.assertIn('editorial', result['pipeline_version'])


if __name__ == '__main__':
    unittest.main()
