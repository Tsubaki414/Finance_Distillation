"""Offline wiring tests. Fake responses are not paid execution/content evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend import account_intelligence as api
from backend.content_dashboard import app
from live.account_intelligence import Store
from live.account_source_adaptation import AccountSourcePipeline, _account, adapt_source
from live.account_sources import SourcePipeline, ingest
from live.content_stages import ContentStages, LOCALIZE, MODEL, VERSION, follow_up_repairs
from ml import budget
from tests.test_account_source_adaptation import FakeClient, EN, ZH, source



def assembled_call(stages, stage, messages, max_tokens):
    """P0-2: stage clients no longer mutate requests; assembly happens once."""
    from live import prompt_assembly
    sent, _ = prompt_assembly.assemble(stage, messages[0]['content'], json.loads(messages[1]['content']),
                                       stage_context=stages.prompt_context(stage))
    return stages(stage, sent, max_tokens)

class ContentStagesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        provider = patch.dict('os.environ', {'ACCOUNT_CONTENT_PROVIDER': 'apify_openrouter'})
        provider.start()
        self.addCleanup(provider.stop)

    def test_relay_selection_is_explicit_lazy_and_records_actual_model(self):
        relay_env = {'ACCOUNT_CONTENT_PROVIDER': 'erisedai_relay',
                     'ACCOUNT_RELAY_BASE_URL': 'https://relay.example/v1',
                     'ACCOUNT_RELAY_API_KEY': 'not-a-real-key',
                     'ACCOUNT_RELAY_MODEL': 'claude-opus-5'}
        sent = []
        fake = FakeClient()
        def respond(stage, messages, ceiling):
            sent.append((stage, copy.deepcopy(messages)))
            return fake(stage, messages, ceiling)
        with patch.dict('os.environ', relay_env), \
                patch('live.content_stages.ApifyClient', side_effect=AssertionError('No fallback')), \
                patch('live.content_stages.ErisedaiClient', return_value=respond) as transport:
            stages = ContentStages(self.root / 'calls')
            transport.assert_not_called()
            self.assertEqual(stages.configuration['provider'], 'erisedai_relay')
            self.assertEqual(stages.configuration['model'], 'claude-opus-5')
            self.assertEqual(stages.configuration['response_format'], {'type': 'json_object'})
            self.assertNotIn('not-a-real-key', json.dumps(stages.configuration))
            result = adapt_source(source(), 'en_morris_archive', self.root, client=stages)
        self.assertEqual(result['stage_configuration']['provider'], 'erisedai_relay')
        self.assertEqual(result['final_draft'], EN)
        self.assertEqual(dict(sent)['localization'][0]['content'], LOCALIZE)
        transport.assert_called_once()

    def test_json_mode_configuration_is_provider_specific_and_not_mutable(self):
        self.assertNotIn('response_format', ContentStages(self.root, client=Mock()).configuration)
        with patch.dict('os.environ', {'ACCOUNT_CONTENT_PROVIDER': 'erisedai_relay'}), \
                patch('live.content_stages.relay_config', return_value={'model': 'claude-opus-5'}):
            stages = ContentStages(self.root, client=Mock())
            observed = stages.configuration
            observed['response_format']['type'] = 'text'
            self.assertEqual(stages.configuration['response_format'], {'type': 'json_object'})

    def test_json_mode_recovery_requires_old_relay_format_and_saved_unrefused_stop(self):
        inherited = {'name': 'localization_capacity', 'selected_from_run': 'length-parent'}
        original = {'id': 'original-relay-invalid-json',
            'stage_configuration': {'provider': 'erisedai_relay', 'execution_repairs': [inherited]},
            'source_adaptation': {'draft_status': 'blocked',
                'execution_failure': {'stage': 'localization', 'code': 'invalid_json'},
                'attempt': {'model_responses': [{'stage': 'localization', 'finish_reason': 'stop',
                                                'refusal': None, 'text': '{"bad":"unescaped"quote"}'}]}}}
        cases = [
            ('old-absent', {}, {}, {}, True),
            ('old-text', {'response_format': {'type': 'text'}}, {}, {}, True),
            ('already-json', {'response_format': {'type': 'json_object'}}, {}, {}, False),
            ('other-provider', {'provider': 'apify_openrouter'}, {}, {}, False),
            ('unknown-provider', {'provider': None}, {}, {}, False),
            ('refusal', {}, {}, {'refusal': 'refused'}, False),
            ('content-filter', {}, {}, {'finish_reason': 'content_filter'}, False),
            ('length', {}, {}, {'finish_reason': 'length'}, False),
            ('missing-stop', {}, {}, {'finish_reason': None}, False),
            ('semantic-hold', {}, {'draft_status': 'held'}, {}, False),
            ('skip', {}, {'draft_status': 'skipped'}, {}, False),
            ('schema-failure', {}, {'execution_failure': {'stage': 'localization',
                                                        'code': 'model_response_contract'}}, {}, False),
            ('source-hold', {}, {'execution_failure': {'stage': 'localization',
                                                     'code': 'source_contract'}}, {}, False),
            ('no-response', {}, {'attempt': {'model_responses': []}}, {}, False),
        ]
        for name, configuration, adaptation, response, eligible in cases:
            with self.subTest(name=name):
                parent = copy.deepcopy(original)
                parent['stage_configuration'].update(configuration)
                parent['source_adaptation']['attempt']['model_responses'][0].update(response)
                parent['source_adaptation'].update(adaptation)
                frozen = copy.deepcopy(parent)
                repairs = follow_up_repairs(parent)
                self.assertEqual(parent, frozen)
                self.assertEqual(repairs[0], inherited)
                self.assertEqual([r['name'] for r in repairs],
                                 ['localization_capacity'] + (['json_response_mode'] if eligible else []))
                if eligible:
                    self.assertEqual(repairs[-1]['selected_from_run'], parent['id'])
                    self.assertEqual(repairs[-1]['failure'], parent['source_adaptation']['execution_failure'])
                    self.assertEqual(repairs[-1]['response_format_change'], {
                        'previous': configuration.get('response_format'),
                        'requested': {'type': 'json_object'}})
                    parent['stage_configuration']['execution_repairs'] = repairs
                    self.assertEqual(follow_up_repairs(parent), repairs)
                    parent['stage_configuration']['response_format'] = {'type': 'json_object'}
                    self.assertEqual(follow_up_repairs(parent), repairs)

    def test_json_mode_repair_preserves_inherited_prompts_payload_and_caps(self):
        from live.distillation_prompts import TRANSLATE
        inherited = [{'name': 'hygiene_contract', 'selected_from_run': 'hygiene-parent'},
                     {'name': 'translation_json_contract', 'selected_from_run': 'translation-parent'}]
        parent = {'id': 'empty-relay-stop',
            'stage_configuration': {'provider': 'erisedai_relay', 'execution_repairs': inherited},
            'source_adaptation': {'draft_status': 'blocked',
                'execution_failure': {'stage': 'translation', 'code': 'invalid_json'},
                'attempt': {'model_responses': [{'stage': 'translation', 'finish_reason': 'stop',
                                                'text': '', 'refusal': None}]}}}
        repairs = follow_up_repairs(parent)
        self.assertEqual(repairs[:-1], inherited)
        self.assertEqual(repairs[-1]['name'], 'json_response_mode')
        messages = [{'role': 'system', 'content': TRANSLATE},
                    {'role': 'user', 'content': json.dumps({'selected_passages': [
                        {'paragraph_id': 'P1', 'exact_text': 'The unchanged source.'}]})}]
        ordinary, recovered = Mock(return_value={}), Mock(return_value={})
        with patch.dict('os.environ', {'ACCOUNT_CONTENT_PROVIDER': 'erisedai_relay'}), \
                patch('live.content_stages.relay_config', return_value={'model': 'claude-opus-5'}):
            ContentStages(self.root, client=ordinary, execution_repairs=inherited)(
                'translation', messages, 4066)
            stages = ContentStages(self.root, client=recovered, execution_repairs=repairs)
            stages('translation', messages, 4066)
        self.assertEqual(ordinary.call_args, recovered.call_args)
        self.assertEqual(recovered.call_count, 1)
        self.assertEqual(recovered.call_args.args[2], 4066)
        self.assertEqual(stages.configuration['execution_repairs'], repairs)

    def test_unknown_provider_is_an_explicit_failure(self):
        with patch.dict('os.environ', {'ACCOUNT_CONTENT_PROVIDER': 'unknown'}), \
                self.assertRaisesRegex(ValueError, 'no provider fallback'):
            ContentStages(self.root / 'calls')

    def test_transport_json_failure_remains_recoverable(self):
        stages = ContentStages(self.root / 'calls', client=Mock(
            side_effect=json.JSONDecodeError('Invalid relay JSON', '', 0)))
        result = adapt_source(source(), 'en_morris_archive', self.root, client=stages)
        self.assertEqual(result['execution_failure']['code'], 'invalid_json')
        self.assertEqual(result['draft_status'], 'blocked')

    def test_followup_repair_selection_is_narrow_and_preserves_failure_evidence(self):
        for stage, code, finish, expected in [
            ('source_hygiene', 'response_incomplete', 'length', 'hygiene_contract'),
            ('source_hygiene', 'invalid_json', 'stop', 'hygiene_contract'),
            ('qa', 'response_incomplete', 'length', 'qa_capacity'),
            ('routing', 'response_incomplete', 'length', 'routing_capacity'),
            ('selection', 'response_incomplete', 'length', 'selection_capacity'),
            ('source_hygiene', 'source_contract', 'stop', None),
            ('source_hygiene', 'content_filter', 'content_filter', None),
            ('qa', 'response_incomplete', None, None),
            ('translation', 'invalid_json', 'stop', 'translation_json_contract'),
            ('translation', 'invalid_json', None, None),
            ('translation', 'invalid_json', 'content_filter', None),
            ('translation', 'model_response_contract', 'stop', None),
            ('translation', 'response_incomplete', 'length', None),
            ('localization', 'response_incomplete', 'length', 'localization_capacity'),
            ('localization', 'response_incomplete', 'stop', None),
            ('localization', 'invalid_json', 'stop', None),
            ('localization', 'content_filter', 'content_filter', None),
        ]:
            with self.subTest(stage=stage, code=code, finish=finish):
                parent = {'id': 'original-run', 'source_adaptation': {
                    'draft_status': 'blocked', 'execution_failure': {'stage': stage, 'code': code},
                    'attempt': {'model_responses': [{'stage': stage, 'finish_reason': finish}]}}}
                frozen = copy.deepcopy(parent)
                repairs = follow_up_repairs(parent)
                self.assertEqual([r['name'] for r in repairs], [expected] if expected else [])
                self.assertEqual(parent, frozen)
                if expected:
                    self.assertEqual(repairs[0]['selected_from_run'], 'original-run')
                    self.assertEqual(repairs[0]['failure']['code'], code)

    def test_routing_followup_uses_existing_ceiling_without_prompt_changes(self):
        messages = [{'role': 'system', 'content': 'UNCHANGED ROUTING PROMPT'},
                    {'role': 'user', 'content': '{}'}]
        ordinary, repaired = Mock(return_value={}), Mock(return_value={})
        ContentStages(self.root, client=ordinary)('routing', messages, 1000)
        stages = ContentStages(self.root, client=repaired, execution_repairs=[{
            'name': 'routing_capacity', 'response_token_ceiling': 1600}])
        stages('routing', messages, 1000)
        self.assertEqual(ordinary.call_args.args[2], 1000)
        self.assertEqual(repaired.call_args.args[2], 1600)
        self.assertEqual(ordinary.call_args.args[1], repaired.call_args.args[1])
        self.assertEqual(repaired.call_count, 1)

    def test_localization_length_repair_changes_only_response_capacity_once(self):
        inherited = {'name':'translation_json_contract','selected_from_run':'original-json-failure'}
        parent = {'id':'original-localization-length',
            'stage_configuration':{'execution_repairs':[inherited]},
            'source_adaptation':{'draft_status':'blocked',
                'execution_failure':{'stage':'localization','code':'response_incomplete'},
                'attempt':{'model_responses':[{'stage':'localization','finish_reason':'length','text':'',
                    'usage':{'completion_tokens':5000}}]}}}
        frozen = copy.deepcopy(parent)
        repairs = follow_up_repairs(parent)
        self.assertEqual([r['name'] for r in repairs],['translation_json_contract','localization_capacity'])
        self.assertEqual(repairs[-1]['response_token_ceiling'],11000)
        self.assertEqual(repairs[-1]['selected_from_run'],parent['id'])
        self.assertEqual(parent,frozen)
        parent['stage_configuration']['execution_repairs']=repairs
        self.assertEqual(follow_up_repairs(parent),repairs)
        messages = [{'role':'system','content':'Existing full localization prompt'},
            {'role':'user','content':json.dumps({'translation':{'text':'The faithful translation.'},
              'selected_passages':[{'paragraph_id':'P1','exact_text':'Original argument.'}]})}]
        ordinary,repaired = Mock(return_value={}),Mock(return_value={})
        assembled_call(ContentStages(self.root,client=ordinary,execution_repairs=[inherited]),'localization',messages,12000)
        assembled_call(ContentStages(self.root,client=repaired,execution_repairs=repairs),'localization',messages,12000)
        self.assertEqual(ordinary.call_args.args[1],repaired.call_args.args[1])
        self.assertEqual(repaired.call_args.args[1][0]['content'],LOCALIZE)
        self.assertEqual((ordinary.call_args.args[2],repaired.call_args.args[2]),(5000,11000))
        self.assertEqual((ordinary.call_count,repaired.call_count),(1,1))

    def test_translation_json_repair_only_adds_serialization_guidance_once(self):
        from live.distillation_prompts import TRANSLATE
        from live.model_json import parse_object
        inherited = {'name':'hygiene_contract','selected_from_run':'original-hygiene-failure'}
        parent = {'id':'original-translation-json-failure',
            'stage_configuration':{'execution_repairs':[inherited]},
            'source_adaptation':{'draft_status':'blocked',
                'execution_failure':{'stage':'translation','code':'invalid_json'},
                'attempt':{'model_responses':[{'stage':'translation','finish_reason':'stop'}]}}}
        frozen = copy.deepcopy(parent)
        repairs = follow_up_repairs(parent)
        self.assertEqual([r['name'] for r in repairs],['hygiene_contract','translation_json_contract'])
        self.assertEqual(repairs[1]['selected_from_run'],parent['id'])
        self.assertEqual(parent,frozen)
        parent['stage_configuration']['execution_repairs'] = repairs
        self.assertEqual(follow_up_repairs(parent),repairs)
        malformed = {'text':'{"segments":[{"paragraph_id":"P1","text":"原文中的"引语"。"}]}',
                     'finish_reason':'stop'}
        ordinary, repaired = Mock(return_value=malformed), Mock(return_value=malformed)
        payload = {'selected_passages':[{'paragraph_id':'P1','exact_text':'The original "quotation".'}],
                   'source_language':'en','target_language':'zh'}
        messages = [{'role':'system','content':TRANSLATE},
                    {'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
        original_messages = copy.deepcopy(messages)
        assembled_call(ContentStages(self.root,client=ordinary,execution_repairs=[inherited]),'translation',messages,9000)
        output = assembled_call(ContentStages(self.root,client=repaired,execution_repairs=repairs),'translation',messages,9000)
        plain_request, repaired_request = ordinary.call_args.args, repaired.call_args.args
        self.assertEqual(plain_request[1][0]['content'],TRANSLATE)
        self.assertTrue(repaired_request[1][0]['content'].startswith(TRANSLATE+'\n\n'))
        self.assertIn('correctly escape embedded quotation marks',repaired_request[1][0]['content'])
        self.assertEqual(plain_request[1][1],repaired_request[1][1])
        self.assertEqual((plain_request[2],repaired_request[2]),(5000,5000))
        self.assertEqual(messages,original_messages)
        self.assertEqual(repaired.call_count,1)
        self.assertEqual(output,malformed)
        with self.assertRaises(json.JSONDecodeError):
            parse_object(output['text'])

    def test_observed_selection_length_followup_inherits_hygiene_and_uses_existing_ceiling(self):
        inherited = {'name': 'hygiene_contract', 'selected_from_run': 'earlier-hygiene-failure'}
        parent = {'id': 'run-39b1e80b91e54d36b811ed6ae447ee32',
                  'stage_configuration': {'execution_repairs': [inherited]},
                  'source_adaptation': {'draft_status': 'blocked',
                      'execution_failure': {'stage': 'selection', 'code': 'response_incomplete'},
                      'attempt': {'model_responses': [{'stage': 'selection', 'finish_reason': 'length',
                          'usage': {'completion_tokens': 1800,
                                    'completion_tokens_details': {'reasoning_tokens': 1718}}}]}}}
        repairs = follow_up_repairs(parent)
        self.assertEqual(repairs[0], inherited)
        self.assertEqual(repairs[1]['name'], 'selection_capacity')
        self.assertEqual(repairs[1]['selected_from_run'], parent['id'])
        self.assertEqual(repairs[1]['response_token_ceiling'], 2200)
        messages = [{'role': 'system', 'content': 'Selection input'},
                    {'role': 'user', 'content': '{}'}]
        ordinary, repaired = Mock(return_value={}), Mock(return_value={})
        ContentStages(self.root, client=ordinary)('selection', messages, 1800)
        ContentStages(self.root, client=repaired, execution_repairs=repairs)(
            'selection', messages, 1800)
        self.assertEqual(ordinary.call_args.args[2], 1800)
        self.assertEqual(repaired.call_args.args[2], 2200)
        self.assertEqual(ordinary.call_args.args[1], repaired.call_args.args[1])
        self.assertEqual(repaired.call_count, 1)
        parent['stage_configuration']['execution_repairs'] = repairs
        self.assertEqual(follow_up_repairs(parent), repairs, 'Same repair is never repeatedly appended')

    def test_automatic_followup_repairs_preserve_parent_and_accumulate_per_stage(self):
        store = Store(self.root / 'store')
        row = {**source(), 'fetched_at': '2026-09-30T12:00:00Z',
               'media_dependencies': [{'type': 'image', 'status': 'uncertain_dependency', 'id': 'test-image'}]}
        candidate = ingest(store, 'en_morris_archive', row)['candidate']
        executions = []

        def factory(directory):
            ordinal = len(executions)
            sent = []
            executions.append(sent)
            fake = FakeClient()
            def respond(stage, messages, ceiling):
                sent.append((stage, copy.deepcopy(messages), ceiling))
                if (ordinal == 0 and stage == 'source_hygiene') or (ordinal == 1 and stage == 'qa'):
                    return {'text': '{"unfinished":', 'finish_reason': 'length'}
                return fake(stage, messages, ceiling)
            return respond

        runner = SourcePipeline(store)
        with patch('live.content_stages.ApifyClient', side_effect=factory):
            first = runner.run('en_morris_archive', candidate['id'])
            frozen_first = copy.deepcopy(store.get('runs', first['id']))
            self.assertEqual(first['source_adaptation']['execution_failure']['stage'], 'source_hygiene')
            self.assertEqual(first['execution_repairs'], [])
            self.assertEqual(runner.run('en_morris_archive', candidate['id'])['id'], first['id'])
            self.assertEqual(len(executions), 1, 'No silent retries when the original attempt fails')
            second = runner.run('en_morris_archive', candidate['id'], first['id'])
            frozen_second = copy.deepcopy(store.get('runs', second['id']))
            self.assertEqual(second['source_adaptation']['execution_failure']['stage'], 'qa')
            third = runner.run('en_morris_archive', candidate['id'], second['id'])
        self.assertEqual(second['follow_up_of'], first['id'])
        self.assertEqual(third['follow_up_of'], second['id'])
        self.assertEqual(store.get('runs', first['id']), frozen_first)
        self.assertEqual(store.get('runs', second['id']), frozen_second)
        repairs = third['stage_configuration']['execution_repairs']
        self.assertEqual([r['name'] for r in repairs], ['hygiene_contract', 'qa_capacity'])
        self.assertEqual([r['selected_from_run'] for r in repairs], [first['id'], second['id']])
        self.assertEqual(third['execution_repairs'], repairs)
        self.assertEqual(third['source_adaptation']['follow_up_of'], second['id'])
        for index, sent in enumerate(executions):
            stages = [s for s, _, _ in sent]
            self.assertEqual(len(stages), len(set(stages)), 'At most one actual call per stage per run')
            if index < 2:
                hygiene = next(m[0]['content'] for s, m, _ in sent if s == 'source_hygiene')
                self.assertEqual('This call returns only the private annotation decisions.' in hygiene, index > 0)
            else:
                self.assertEqual(stages, ['qa'], 'QA execution recovery cannot regenerate upstream content')
        for field in ('selection', 'translation', 'localization', 'final_draft'):
            self.assertEqual(third['source_adaptation'][field], second['source_adaptation'][field])
        self.assertEqual(third['execution_checkpoint']['parent_run_id'], second['id'])
        self.assertFalse(third['execution_checkpoint']['upstream_regeneration_permitted'])
        third_source = third['source_adaptation']['source']
        second_source = second['source_adaptation']['source']
        self.assertEqual({k:v for k,v in third_source.items() if k != 'snapshot_at'},
                         {k:v for k,v in second_source.items() if k != 'snapshot_at'})
        self.assertEqual(next(c for s, _, c in executions[2] if s == 'qa'), 11000)
        self.assertEqual(len(store.rows('runs')), 3)

    def test_default_adaptation_cannot_activate_repairs_without_followup(self):
        with self.assertRaisesRegex(ValueError, 'explicit follow-up'):
            adapt_source(source(), 'en_morris_archive', self.root, execution_repairs=[{'name': 'qa_capacity'}])

    def test_default_is_validated_provider_and_initialization_has_no_network(self):
        with patch('live.content_stages.ApifyClient') as transport, \
                patch('live.distillation.RelayClient', side_effect=AssertionError('Old relay must not run')):
            pipeline = AccountSourcePipeline(self.root, _account('en_morris_archive'))
            self.assertIsInstance(pipeline.client, ContentStages)
            self.assertEqual(pipeline.client.configuration['model'], MODEL)
            self.assertEqual(pipeline.client.configuration['version'], VERSION)
            transport.assert_not_called()

    def test_default_source_pipeline_saves_current_configuration_and_exact_input(self):
        store = Store(self.root / 'store')
        admitted = ingest(store, 'en_morris_archive', {
            **source(), 'fetched_at': '2026-09-30T12:00:00Z'})['candidate']
        original = copy.deepcopy(source())
        sent = []
        fake = FakeClient()

        def respond(stage, messages, ceiling):
            sent.append((stage, copy.deepcopy(messages)))
            return fake(stage, messages, ceiling)

        with patch('live.content_stages.ApifyClient', return_value=respond), \
                patch('live.distillation.RelayClient', side_effect=AssertionError('Old relay must not run')):
            run = SourcePipeline(store).run('en_morris_archive', admitted['id'])
        self.assertEqual(run['candidates'][0]['text'], EN)
        self.assertEqual(run['human_status'], 'pending')
        self.assertFalse(run['publishing_enabled'])
        self.assertEqual(store.get('runs', run['id'])['id'], run['id'])
        result = run['source_adaptation']
        self.assertEqual(result['generation_protocol'], VERSION)
        self.assertEqual(result['stage_configuration']['provider'], 'apify_openrouter')
        localize = dict(sent)['localization']
        self.assertEqual(localize[0]['content'], LOCALIZE)
        payload = json.loads(localize[1]['content'])
        self.assertEqual(payload['selected_passages'][0]['exact_text'], original['original_text'])
        self.assertEqual(payload['translation']['text'], EN)
        self.assertEqual(payload['target_language'], 'en')
        self.assertIn('source_hygiene_decisions', payload)

    def test_budget_failure_is_saved_without_relay_fallback_or_cap_mutation(self):
        cap_before = budget.cap()
        transport = Mock(side_effect=budget.BudgetExceeded('TEST configured cap'))
        stages = ContentStages(self.root / 'calls', client=transport)
        with patch('live.distillation.RelayClient', side_effect=AssertionError('No fallback')):
            result = adapt_source(source(), 'en_morris_archive', self.root, client=stages)
        self.assertEqual(result['execution_failure']['code'], 'budget_exhausted')
        self.assertEqual(result['execution_failure']['stage'], 'routing')
        self.assertEqual(result['draft_status'], 'blocked')
        self.assertEqual(result['final_draft'], '')
        self.assertTrue(Path(result['result_path']).is_file())
        self.assertEqual(budget.cap(), cap_before)
        self.assertEqual(transport.call_count, 1)

    def test_refusal_and_invalid_json_remain_distinct_recoverable_outcomes(self):
        for response, code in [
            ({'text': '', 'finish_reason': 'content_filter'}, 'content_filter'),
            ({'text': '{invalid', 'finish_reason': 'stop'}, 'invalid_json'),
            ({'text': '{unfinished', 'finish_reason': 'length'}, 'response_incomplete'),
            ({'text': '{"decision":"UNDECLARED"}', 'finish_reason': 'stop'}, 'model_response_contract'),
        ]:
            with self.subTest(code=code):
                client = ContentStages(self.root / 'calls', client=Mock(return_value=response))
                result = adapt_source(source(), 'en_morris_archive', self.root / code, client=client)
                self.assertEqual(result['execution_failure']['code'], code)
                self.assertEqual(result['human_review']['status'], 'pending')
                self.assertEqual(result['final_draft'], '')

    def test_actual_account_dashboard_generation_uses_shared_default(self):
        store = Store(self.root / 'store')
        candidate = ingest(store, 'en_morris_archive', {
            **source(), 'fetched_at': '2026-09-30T12:00:00Z'})['candidate']
        fake = FakeClient()
        with patch.object(api, 'STORE', store), \
                patch('live.content_stages.ApifyClient', return_value=fake), \
                patch('live.distillation.RelayClient', side_effect=AssertionError('No old writer')):
            response = TestClient(app).post(
                '/api/account-intelligence/accounts/en_morris_archive/inbox/' + candidate['id'] + '/run',
                json={})
        self.assertEqual(response.status_code, 200, response.text)
        run = response.json()
        self.assertEqual(run['source_adaptation']['generation_protocol'], VERSION)
        self.assertEqual(run['candidates'][0]['text'], EN)
        self.assertEqual(store.get('runs', run['id'])['candidates'][0]['text'], EN)

    def test_historical_desk_cannot_invoke_the_retired_writer(self):
        with patch('live.editorial.EditorialPipeline', side_effect=AssertionError('Retired writer')):
            response = TestClient(app).post('/api/content-workbench/sources/anything/generate')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['code'], 'legacy_generation_disabled')
        self.assertEqual(response.json()['detail']['dashboard'], '/account-intelligence')


if __name__ == '__main__':
    unittest.main()
