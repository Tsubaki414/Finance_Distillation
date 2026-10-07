"""COMPOSE/STANCE model + relay are configurable without code edits.

Shipped defaults (stage-models-v3-gemini-official, Oct 7): compose/stance/extract/extract_flash/view_enrich on
gemini-3-flash-preview via the official Gemini API, no fallback; other stages claude-opus-5 on the configured
relay. Routing-machinery tests use the frozen v2 (micuapi) table in tests/fixtures. An override names a model,
optionally an HTTPS base URL and the *name* of the env var holding its key;
a key name is bound to its relay host (a key is never sent to another host).
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from live import stage_models
from live.erisedai_distillation_client import ErisedaiClient
from ml import budget

MICU = 'https://www.micuapi.ai/v1'
GEMINI = 'https://generativelanguage.googleapis.com/v1beta'
V2 = Path(__file__).parent / 'fixtures' / 'stage_models_v2_micuapi.json'
FAKE_GEMINI_ENV = 'prefix-AQ.fakeTOKEN123'


class OverrideTableTests(unittest.TestCase):
    def test_no_env_keeps_shipped_defaults(self):
        table = stage_models.from_env(stage_models.load(), {})
        # Oct 7 (v3): compose / stance / extract on gemini-3-flash-preview, official Gemini API, no fallback.
        for stage in ('compose', 'stance', 'extract'):
            # temperature 1.0 + thinking medium: at 0.0 Gemini 3 flash looped in thinking (Oct 7 smoke)
            self.assertEqual(stage_models.for_stage(table, stage), {'model': 'gemini-3-flash-preview', 'temperature': 1.0})
            self.assertEqual(stage_models.thinking_level(table, stage, {}), 'medium')
            self.assertEqual(stage_models.route(table, stage), {'base_url': GEMINI, 'api_key_env': 'GEMINI_API_KEY'})
            self.assertIsNone(stage_models.fallback(table, stage))
        self.assertEqual(stage_models.for_stage(table, 'qa'), {'model': 'claude-opus-5', 'temperature': 0.0})
        self.assertIsNone(stage_models.route(table, 'qa'))

    def test_env_overrides_compose_only(self):
        env = {'FD_COMPOSE_MODEL': 'gpt-6.1-sol', 'FD_COMPOSE_BASE_URL': MICU,
               'FD_COMPOSE_API_KEY_ENV': 'GEMINI_RELAY_API_KEY'}
        table = stage_models.from_env(stage_models.load(V2), env)
        self.assertEqual(stage_models.for_stage(table, 'compose')['model'], 'gpt-6.1-sol')
        self.assertEqual(stage_models.route(table, 'compose'),
                         {'base_url': MICU, 'api_key_env': 'GEMINI_RELAY_API_KEY'})
        self.assertEqual(stage_models.for_stage(table, 'stance')['model'], 'claude-opus-5')
        self.assertEqual(stage_models.accepted(table, 'gpt-6.1-sol'), ['gpt-6.1-sol'])

    def test_env_stance_override_and_accepted_names(self):
        env = {'FD_STANCE_MODEL': 'claude-opus-5-5', 'FD_STANCE_ACCEPTED_MODELS': 'claude-opus-5-5,anthropic/claude-opus-5-5'}
        table = stage_models.from_env(stage_models.load(), env)
        self.assertEqual(stage_models.for_stage(table, 'stance')['model'], 'claude-opus-5-5')
        self.assertIsNone(stage_models.route(table, 'stance'))
        self.assertIn('anthropic/claude-opus-5-5', stage_models.accepted(table, 'claude-opus-5-5'))

    def test_base_url_without_model_is_rejected(self):
        with self.assertRaises(ValueError):
            stage_models.from_env(stage_models.load(), {'FD_COMPOSE_BASE_URL': MICU,
                                                        'FD_COMPOSE_API_KEY_ENV': 'GEMINI_RELAY_API_KEY'})

    def test_base_url_and_key_env_come_together(self):
        with self.assertRaises(ValueError):
            stage_models.override(stage_models.load(), 'compose', 'gpt-6.1-sol', base_url=MICU)
        with self.assertRaises(ValueError):
            stage_models.override(stage_models.load(), 'compose', 'gpt-6.1-sol', api_key_env='GEMINI_RELAY_API_KEY')

    def test_key_is_bound_to_its_host(self):
        with self.assertRaises(ValueError):
            stage_models.override(stage_models.load(), 'compose', 'm', base_url='https://evil.example/v1',
                                  api_key_env='GEMINI_RELAY_API_KEY')
        with self.assertRaises(ValueError):
            stage_models.override(stage_models.load(), 'compose', 'm', base_url=MICU, api_key_env='RELAY_API_KEY')
        with self.assertRaises(ValueError):
            stage_models.override(stage_models.load(), 'compose', 'm', base_url=MICU, api_key_env='HOME')

    def test_insecure_or_credentialed_url_rejected(self):
        for url in ('http://www.micuapi.ai/v1', 'https://u:p@www.micuapi.ai/v1', 'https://www.micuapi.ai/v1?k=1'):
            with self.assertRaises(ValueError):
                stage_models.override(stage_models.load(), 'compose', 'm', base_url=url, api_key_env='GEMINI_RELAY_API_KEY')

    def test_override_does_not_mutate_input_and_validates(self):
        base = stage_models.load()
        snapshot = json.dumps(base, sort_keys=True)
        table = stage_models.override(base, 'compose', 'm2', rates=(3.0, 15.0))
        self.assertEqual(json.dumps(base, sort_keys=True), snapshot)
        stage_models.validate(table)
        self.assertEqual(stage_models.rates(table, 'compose'), (3.0, 15.0))
        with self.assertRaises(ValueError):
            stage_models.override(base, 'compose', 'm2', rates=(-1, 2))


class ClientRoutesStageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        ledger = self.root / 'spend.json'
        ledger.write_text(json.dumps({'cap_usd': 2.0, 'spent_usd': 0.0, 'calls': 0}))
        for name, value in [('LEDGER', ledger), ('DISTILLATION_RUNS', self.root / 'r.jsonl')]:
            p = patch.object(budget, name, value)
            p.start()
            self.addCleanup(p.stop)
        prices = budget.PRICES.copy()
        self.addCleanup(lambda: (budget.PRICES.clear(), budget.PRICES.update(prices)))
        self.seen = []

    def config(self, table):
        return {'base_url': 'https://api.erisedai.com/v1', 'api_key': 'default-key', 'model': 'claude-opus-5',
                'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0, 'stage_models': table}

    def client(self, table):
        def handle(request):
            body = json.loads(request.content)
            self.seen.append((request.url.host, request.headers['authorization'], body['model']))
            return httpx.Response(200, json={'id': 'r', 'model': body['model'],
                                             'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}],
                                             'usage': {'prompt_tokens': 1, 'completion_tokens': 1}})
        return ErisedaiClient(self.root / 'calls', configuration=self.config(table),
                              transport=httpx.MockTransport(handle))

    def test_compose_goes_to_second_relay_with_its_own_key(self):
        table = stage_models.override(stage_models.load(V2), 'compose', 'gpt-6.1-sol', base_url=MICU,
                                      api_key_env='GEMINI_RELAY_API_KEY', rates=(2.0, 8.0))
        with patch.dict(os.environ, {'GEMINI_RELAY_API_KEY': 'second-key'}):
            c = self.client(table)
            c('stance', [{'role': 'user', 'content': 'x'}], 10)
            out = c('compose', [{'role': 'user', 'content': 'x'}], 10)
        self.assertEqual(self.seen, [('api.erisedai.com', 'Bearer default-key', 'claude-opus-5'),
                                     ('www.micuapi.ai', 'Bearer second-key', 'gpt-6.1-sol')])
        self.assertEqual(out['model'], 'gpt-6.1-sol')
        logs = ''.join(p.read_text() for p in (self.root / 'calls').glob('*.json'))
        self.assertNotIn('second-key', logs)
        self.assertNotIn('default-key', logs)
        self.assertIn('www.micuapi.ai', logs)
        self.assertEqual(budget.PRICES['erisedai_relay/gpt-6.1-sol'], (2.0, 8.0))

    def test_missing_routed_key_fails_before_any_call(self):
        # v2 (micuapi) table; the override replaces compose without a fallback, so a missing key must raise.
        table = stage_models.override(stage_models.load(V2), 'compose', 'gpt-6.1-sol', base_url=MICU,
                                      api_key_env='GEMINI_RELAY_API_KEY')
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('GEMINI_RELAY_API_KEY', None)
            with patch('live.erisedai_distillation_client._dotenv', return_value={}):
                with self.assertRaises(ValueError):
                    self.client(table)
        self.assertEqual(self.seen, [])

    def test_env_override_applies_when_no_inline_table(self):
        # Shipped v3 table + FD_COMPOSE_MODEL=claude-opus-5-5: compose leaves Gemini for the default relay,
        # stance stays on the official Gemini API.
        def handle(request):
            if request.url.host == 'generativelanguage.googleapis.com':
                self.seen.append(('gemini', request.url.path.rsplit('/', 1)[-1]))
                return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': '{}'}]},
                                                                 'finishReason': 'STOP'}],
                                                 'usageMetadata': {'promptTokenCount': 1, 'candidatesTokenCount': 1},
                                                 'modelVersion': 'gemini-3-flash-preview'})
            model = json.loads(request.content)['model']
            self.seen.append((request.url.host, model))
            return httpx.Response(200, json={'id': 'r', 'model': model,
                                             'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}],
                                             'usage': {'prompt_tokens': 1, 'completion_tokens': 1}})
        env = {'FD_COMPOSE_MODEL': 'claude-opus-5-5', 'GEMINI_API_KEY': FAKE_GEMINI_ENV}
        with patch.dict(os.environ, env):
            for k in ('FD_GEMINI_MODEL', 'FD_GEMINI_ONLY', 'FD_STANCE_MODEL', 'FD_EXTRACT_MODEL'):
                os.environ.pop(k, None)
            c = ErisedaiClient(self.root / 'calls', configuration={k: v for k, v in self.config(None).items() if k != 'stage_models'},
                               transport=httpx.MockTransport(handle))
            c('compose', [{'role': 'user', 'content': 'x'}], 10)
            c('stance', [{'role': 'user', 'content': 'x'}], 10)
        self.assertEqual(self.seen, [('api.erisedai.com', 'claude-opus-5-5'),
                                     ('gemini', 'gemini-3-flash-preview:generateContent')])

if __name__ == '__main__':
    unittest.main()
