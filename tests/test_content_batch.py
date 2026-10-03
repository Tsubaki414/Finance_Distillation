import hashlib
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.run_content_batch import BatchStages, LOCALIZE, ResumePrefix, validate_item, execute



def assembled_call(stages, stage, messages, max_tokens):
    """P0-2: stage clients no longer mutate requests; assembly happens once."""
    from live import prompt_assembly
    sent, _ = prompt_assembly.assemble(stage, messages[0]['content'], json.loads(messages[1]['content']),
                                       stage_context=stages.prompt_context(stage))
    return stages(stage, sent, max_tokens)

class ContentBatchTests(unittest.TestCase):
    def test_followup_of_reingested_source_keeps_explicit_parent_not_cached_result(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            folder = base / 'source_selection/zh_industry'; folder.mkdir(parents=True)
            (folder / 'selected_sources.json').write_text(json.dumps({'sources': [{
                'selection_id': 'I04', 'source': {'original_text': 'Exact original.',
                    'source_id': 'semianalysis', 'content_complete': True}}]}))
            outcomes = base / 'outcomes/zh_industry'; outcomes.mkdir(parents=True)
            adaptation = base / 'original.json'
            adaptation.write_text(json.dumps({'attempt': {'account_context': {'as_of': 'original'}}}))
            parent = {'run_id': 'original-run', 'adaptation_path': str(adaptation),
                      'nonempty_draft': True, 'final_draft': 'Unchanged.', 'account_id': 'zh_industry',
                      'source_hash': hashlib.sha256(b'Exact original.').hexdigest(),
                      'admission': {'admitted': True, 'candidate': {'id': 'original-inbox'}}}
            target = outcomes / 'I04.json'; target.write_text(json.dumps(parent))
            history = outcomes / 'history'; history.mkdir()
            (history / 'I04-original-run.json').write_text(json.dumps(parent))
            pipeline = Mock()
            pipeline.run.return_value = {'id': 'new-run', 'follow_up_of': 'original-run',
                'status': 'machine_hold', 'candidates': [{'text': 'Unchanged.', 'machine_fidelity_pass': False}]}
            store = Mock(); store.rows.return_value = []  # new inbox has no prior run
            with patch('scripts.run_content_batch.BASE', base), \
                 patch('scripts.run_content_batch.Store', return_value=store), \
                 patch('scripts.run_content_batch.ingest', return_value={
                     'admitted': True, 'candidate': {'id': 'new-inbox'}}) as ingest_call, \
                 patch('scripts.run_content_batch.BatchStages'), \
                 patch('scripts.run_content_batch.SourcePipeline', return_value=pipeline), \
                 patch('scripts.run_content_batch.budget.remaining', return_value=2):
                execute('zh_industry', limit=1, follow_up='I04', resume_stage='qa', execution_repair='qa_capacity')
                result = json.loads(target.read_text())
                target.write_text(json.dumps(parent))
                pipeline.run.return_value = {'id': 'original-run', 'follow_up_of': None}
                with self.assertRaisesRegex(ValueError, 'cached parent is not a new result'):
                    execute('zh_industry', limit=1, follow_up='I04', resume_stage='qa', execution_repair='qa_capacity')
                self.assertEqual(json.loads(target.read_text()), parent)
                ingest_call.assert_not_called()
            self.assertEqual(pipeline.run.call_args.kwargs['follow_up_of'], 'original-run')
            self.assertEqual(pipeline.run.call_args.args[1], 'original-inbox')
            self.assertEqual(result['follow_up_of'], 'original-run')
            self.assertEqual(json.loads((history / 'I04-original-run.json').read_text()), parent)

    def test_nested_followup_metadata_and_failed_stage_are_not_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            messages = [{'role': 'system', 'content': 'frozen'}, {'role': 'user', 'content': '{}'}]
            records = [[], {'stage': 'translation', 'started_at': '2026-09-30',
                'call_id': 'failed-stage', 'status': 'completed', 'messages': messages,
                'response': {'text': 'invalid JSON', 'finish_reason': 'stop'}},
                {'stage': 'routing', 'started_at': '2026-09-29', 'call_id': 'old',
                 'status': 'completed', 'messages': messages,
                 'response': {'text': 'old routing', 'finish_reason': 'stop'}},
                {'stage': 'routing', 'started_at': '2026-09-30', 'call_id': 'latest',
                 'status': 'completed', 'messages': messages,
                 'response': {'text': 'latest routing', 'finish_reason': 'stop'}}]
            for i, record in enumerate(records):
                p = Path(directory) / f'{i}.json'; p.write_text(json.dumps(record)); paths.append(p)
            from unittest.mock import Mock
            client = Mock()
            resume = ResumePrefix(client, paths, 'translation', directory)
            self.assertEqual(resume('routing', messages, 100)['text'], 'latest routing')
            resume('translation', messages, 100)
            client.assert_called_once_with('translation', messages, 100)

    def test_execution_schema_reminder_retains_rules_and_entire_payload(self):
        with patch('scripts.run_content_batch.ApifyClient') as client:
            stages = BatchStages('/unused', {'_execution_repair': 'hygiene_contract'}, {})
            payload = {'selected_passages': ['exact complete original'], 'annotations': [{'id': 'actual'}]}
            messages = [{'role': 'system', 'content': 'original semantic rules'},
                        {'role': 'user', 'content': json.dumps(payload)}]
            assembled_call(stages, 'source_hygiene', messages, 4500)
            sent = client.return_value.call_args.args[1]
            self.assertTrue(sent[0]['content'].startswith('original semantic rules'))
            self.assertEqual(json.loads(sent[1]['content']), payload)
            self.assertIn('exactly this top-level key', sent[0]['content'])

    def test_resume_reuses_api_response_only_with_same_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            def messages(text, stamp):
                return [{'role': 'system', 'content': 'frozen'}, {'role': 'user', 'content':
                        json.dumps({'source': {'original_text': text, 'snapshot_at': stamp}})}]
            saved = Path(directory) / 'call.json'
            saved.write_text(json.dumps({'stage': 'routing', 'started_at': '2026-09-30',
                'call_id': 'original', 'status': 'completed', 'messages': messages('actual source', 'old'),
                'response': {'text': '{"decision":"MOVE"}', 'finish_reason': 'stop'}}))
            from unittest.mock import Mock
            client = Mock(return_value={'text': 'new network response'})
            resume = ResumePrefix(client, [saved], 'qa', directory)
            self.assertEqual(resume('routing', messages('actual source', 'new'), 100)['text'], '{"decision":"MOVE"}')
            client.assert_not_called()
            resume('routing', messages('changed fact', 'new'), 100)
            client.assert_called_once()
            self.assertEqual(resume.references[0]['original_call_id'], 'original')

    def test_localization_keeps_exact_source_translation_and_hygiene_payload(self):
        with patch('scripts.run_content_batch.ApifyClient') as client:
            stages = BatchStages('/unused', {}, {})
            payload = {'selected_passages': [{'exact_text': '理由与例子'}],
                       'translation': {'text': 'Reasons and examples.'},
                       'source_hygiene_decisions': [{'action': 'attribute'}]}
            messages = [{'role': 'system', 'content': 'old'},
                        {'role': 'user', 'content': json.dumps(payload)}]
            assembled_call(stages, 'localization', messages, 28000)
            stage, sent, limit = client.return_value.call_args.args
            self.assertEqual(stage, 'localization')
            self.assertEqual(sent[0]['content'], LOCALIZE)
            self.assertEqual(json.loads(sent[1]['content']), payload)
            self.assertEqual(messages[0]['content'], 'old')
            self.assertEqual(limit, 5000)

    def test_morris_exception_is_narrow_and_explicit_not_a_single_word_ban(self):
        def item(text):
            return {'source': {'original_text': text, 'content_complete': True}}
        validate_item('en_morris_archive', item('这不是确定的结果。请注意条件。'))
        with self.assertRaises(ValueError):
            validate_item('en_morris_archive', item('关键不是结果，而是过程。'))
        allowed = {**item('关键不是结果，而是过程。'), 'style_exception': {'allowed': True}}
        validate_item('en_morris_archive', allowed)

    def test_official_releases_and_inexact_passages_stop_before_model(self):
        source = {'original_text': 'Exact argument.', 'content_complete': True}
        for item in ({'source': {**source, 'source_id': 'primary_bls'}},
                     {'source': source, 'proposed_passages': [{'start': 0, 'end': 5, 'exact_text': 'Wrong'}]}):
            with self.assertRaises(ValueError): validate_item('zh_macro', item)

    def test_morris_style_exception_is_private_and_qa_keeps_fidelity_requirements(self):
        with patch('scripts.run_content_batch.ApifyClient') as client:
            stages = BatchStages('/unused', {'style_exception': {'allowed': True}}, {})
            messages = [{'role': 'system', 'content': 'Original QA'}, {'role': 'user', 'content': '{}'}]
            assembled_call(stages, 'qa', messages, 6500)
            system = client.return_value.call_args.args[1][0]['content']
            self.assertTrue(system.startswith('Original QA'))
            self.assertIn('all other fidelity and unnecessary-edit checks still apply', system)
            self.assertIn('Do not mention this editing preference in the public text', system)


if __name__ == '__main__': unittest.main()
