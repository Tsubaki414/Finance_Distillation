"""COMPOSE/STANCE model + relay are configurable without code edits.

Defaults stay claude-opus-5 on the configured relay. An override names a model,
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


class OverrideTableTests(unittest.TestCase):
    def test_no_env_keeps_shipped_defaults(self):
        table = stage_models.from_env(stage_models.load(), {})
        for stage in ('compose', 'stance', 'extract'):
            self.assertEqual(stage_models.for_stage(table, stage), {'model': 'claude-opus-5', 'temperature': 0.0})
            self.assertIsNone(stage_models.route(table, stage))

    def test_env_overrides_compose_only(self):
        env = {'FD_COMPOSE_MODEL': 'gpt-6.1-sol', 'FD_COMPOSE_BASE_URL': MICU,
               'FD_COMPOSE_API_KEY_ENV': 'GEMINI_RELAY_API_KEY'}
        table = stage_models.from_env(stage_models.load(), env)
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
        table = stage_models.override(stage_models.load(), 'compose', 'gpt-6.1-sol', base_url=MICU,
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
        table = stage_models.override(stage_models.load(), 'compose', 'gpt-6.1-sol', base_url=MICU,
                                      api_key_env='GEMINI_RELAY_API_KEY')
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('GEMINI_RELAY_API_KEY', None)
            with patch('live.erisedai_distillation_client._dotenv', return_value={}):
                with self.assertRaises(ValueError):
                    self.client(table)
        self.assertEqual(self.seen, [])

    def test_env_override_applies_when_no_inline_table(self):
        with patch.dict(os.environ, {'FD_COMPOSE_MODEL': 'claude-opus-5-5'}):
            c = ErisedaiClient(self.root / 'calls', configuration={k: v for k, v in self.config(None).items() if k != 'stage_models'},
                               transport=httpx.MockTransport(lambda r: (self.seen.append(json.loads(r.content)['model']), httpx.Response(200, json={
                                   'id': 'r', 'model': json.loads(r.content)['model'],
                                   'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}],
                                   'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}))[1]))
            c('compose', [{'role': 'user', 'content': 'x'}], 10)
            c('extract', [{'role': 'user', 'content': 'x'}], 10)
        self.assertEqual(self.seen, ['claude-opus-5-5', 'claude-opus-5'])


if __name__ == '__main__':
    unittest.main()
