"""P0-4 prerequisite (plan 1.4 subset): per-stage model/temperature table.

Defaults keep today's behaviour (every stage claude-opus-5 at 0.0). A stage
override changes the request; a response model outside the configured
mapping is rejected (no silent fallback)."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from live import stage_models
from live.erisedai_distillation_client import ErisedaiClient
from ml import budget


class StageModelTableTests(unittest.TestCase):
    def test_shipped_table_keeps_current_defaults(self):
        table = stage_models.load()
        for stage in ('routing', 'source_hygiene', 'source_selection', 'evergreen_gate',
                      'translation', 'localization', 'qa'):
            self.assertEqual(stage_models.for_stage(table, stage),
                             {'model': 'claude-opus-5', 'temperature': 0.0})

    def test_rejects_model_without_accepted_response_mapping(self):
        bad = {'default': {'model': 'm1', 'temperature': 0.0}, 'stages': {},
               'accepted_response_models': {}}
        with self.assertRaises(ValueError):
            stage_models.validate(bad)

    def test_rejects_out_of_range_temperature(self):
        bad = {'default': {'model': 'm1', 'temperature': 3},
               'stages': {}, 'accepted_response_models': {'m1': ['m1']}}
        with self.assertRaises(ValueError):
            stage_models.validate(bad)


class ClientUsesStageTableTests(unittest.TestCase):
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
        self.table = {'default': {'model': 'claude-opus-5', 'temperature': 0.0},
                      'stages': {'qa': {'model': 'gpt-x', 'temperature': 0.2}},
                      'accepted_response_models': {'claude-opus-5': ['claude-opus-5'],
                                                   'gpt-x': ['gpt-x', 'gpt-x-2026']}}
        self.config = {'base_url': 'https://relay.example/v1', 'api_key': 'k',
                       'model': 'claude-opus-5', 'input_usd_per_million': 15.0,
                       'output_usd_per_million': 75.0, 'stage_models': self.table}
        self.seen = []

    def client(self, reply_model):
        def handle(request):
            body = json.loads(request.content)
            self.seen.append(body)
            return httpx.Response(200, json={
                'id': 'r', 'model': reply_model(body['model']),
                'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1}})
        return ErisedaiClient(self.root / 'calls', configuration=self.config,
                             transport=httpx.MockTransport(handle))

    def test_each_stage_uses_configured_model_and_temperature(self):
        c = self.client(lambda m: 'gpt-x-2026' if m == 'gpt-x' else m)
        msgs = [{'role': 'user', 'content': 'x'}]
        a = c('routing', msgs, 10)
        b = c('qa', msgs, 10)
        self.assertEqual([(s['model'], s['temperature']) for s in self.seen],
                         [('claude-opus-5', 0.0), ('gpt-x', 0.2)])
        self.assertEqual(a['model'], 'claude-opus-5')
        self.assertEqual(b['model'], 'gpt-x')
        self.assertEqual(b['response_model'], 'gpt-x-2026')

    def test_response_model_outside_mapping_is_rejected(self):
        c = self.client(lambda m: 'claude-opus-5' if m == 'gpt-x' else m)
        with self.assertRaises(ValueError):
            c('qa', [{'role': 'user', 'content': 'x'}], 10)

    def test_config_without_table_uses_shipped_defaults(self):
        self.config.pop('stage_models')
        # The shipped table routes Gemini stages to the official API; their key is resolved at construction.
        env = patch.dict('os.environ', {'GEMINI_API_KEY': 'prefix-AQ.fakeTOKEN123'})
        env.start()
        self.addCleanup(env.stop)
        import os
        for k in ('FD_QA_MODEL', 'FD_GEMINI_ONLY'):
            os.environ.pop(k, None)
        c = self.client(lambda m: m)
        c('qa', [{'role': 'user', 'content': 'x'}], 10)
        self.assertEqual((self.seen[0]['model'], self.seen[0]['temperature']), ('claude-opus-5', 0.0))


if __name__ == '__main__':
    unittest.main()
