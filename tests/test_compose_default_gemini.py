"""COMPOSE defaults to gemini-3.1-pro-preview on the micuapi relay (key env GEMINI_RELAY_API_KEY),
with claude-opus-5-5 on the default relay as the documented fallback when Gemini errors,
times out, has no channel, or its key is not configured. Other stages stay claude-opus-5.
A response-model mismatch is never a fallback trigger.
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
MSG = [{'role': 'user', 'content': 'x'}]


def ok(model):
    return httpx.Response(200, json={'id': 'r', 'model': model,
                                     'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}],
                                     'usage': {'prompt_tokens': 1, 'completion_tokens': 1}})


class ShippedTableTests(unittest.TestCase):
    def test_compose_default_is_gemini_on_micuapi(self):
        table = stage_models.load()
        self.assertEqual(stage_models.for_stage(table, 'compose')['model'], 'gemini-3.1-pro-preview')
        self.assertEqual(stage_models.route(table, 'compose'),
                         {'base_url': MICU, 'api_key_env': 'GEMINI_RELAY_API_KEY'})
        self.assertIn('gemini-3.1-pro-preview', stage_models.accepted(table, 'gemini-3.1-pro-preview'))

    def test_other_stages_unchanged(self):
        table = stage_models.load()
        for stage in ('stance', 'translate', 'qa'):
            self.assertEqual(stage_models.for_stage(table, stage)['model'], 'claude-opus-5')
            self.assertIsNone(stage_models.route(table, stage))
        # EXTRACT moved to Gemini on 2026-10-06 (tests/test_gemini_extract.py).
        self.assertEqual(stage_models.for_stage(table, 'extract')['model'], 'gemini-3.1-pro-preview')

    def test_compose_fallback_is_opus_5_5_on_default_relay(self):
        fb = stage_models.fallback(stage_models.load(), 'compose')
        self.assertEqual(fb['model'], 'claude-opus-5-5')
        self.assertIsNone(fb.get('base_url'))
        self.assertIsNone(stage_models.fallback(stage_models.load(), 'stance'))

    def test_env_can_revert_compose_to_opus_5(self):
        table = stage_models.from_env(stage_models.load(), {'FD_COMPOSE_MODEL': 'claude-opus-5'})
        self.assertEqual(stage_models.for_stage(table, 'compose')['model'], 'claude-opus-5')
        self.assertIsNone(stage_models.route(table, 'compose'))
        self.assertIsNone(stage_models.fallback(table, 'compose'))

    def test_fallback_must_be_valid(self):
        table = stage_models.load()
        table['stages']['compose']['fallback'] = {'model': 'unknown-model'}
        with self.assertRaises(ValueError):
            stage_models.validate(table)


class ClientFallbackTests(unittest.TestCase):
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

    def client(self, handler, env=None):
        config = {'base_url': 'https://api.erisedai.com/v1', 'api_key': 'default-key', 'model': 'claude-opus-5',
                  'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0}

        def handle(request):
            body = json.loads(request.content)
            self.seen.append((request.url.host, request.headers['authorization'], body['model']))
            return handler(request.url.host, body['model'])
        environ = {'GEMINI_RELAY_API_KEY': 'gem-key'} if env is None else env
        with patch.dict(os.environ, environ):
            for k in ('FD_COMPOSE_MODEL', 'FD_STANCE_MODEL'):
                os.environ.pop(k, None)
            if 'GEMINI_RELAY_API_KEY' not in environ:
                os.environ.pop('GEMINI_RELAY_API_KEY', None)
            with patch('live.erisedai_distillation_client._dotenv', return_value={}):
                return ErisedaiClient(self.root / 'calls', configuration=config,
                                      transport=httpx.MockTransport(handle))

    def logs(self):
        return [json.loads(p.read_text()) for p in sorted((self.root / 'calls').glob('*.json'))]

    def test_compose_uses_gemini_by_default(self):
        out = self.client(lambda host, model: ok(model))('compose', MSG, 10)
        self.assertEqual(self.seen, [('www.micuapi.ai', 'Bearer gem-key', 'gemini-3.1-pro-preview')])
        self.assertEqual(out['model'], 'gemini-3.1-pro-preview')
        self.assertFalse(out.get('model_fallback'))

    def test_gemini_server_error_falls_back_to_opus_5_5(self):
        def handler(host, model):
            return httpx.Response(503, json={'error': {'message': 'busy'}}) if host == 'www.micuapi.ai' else ok(model)
        out = self.client(handler)('compose', MSG, 10)
        self.assertEqual([s[2] for s in self.seen], ['gemini-3.1-pro-preview', 'claude-opus-5-5'])
        self.assertEqual(self.seen[1][:2], ('api.erisedai.com', 'Bearer default-key'))
        self.assertEqual(out['model'], 'claude-opus-5-5')
        self.assertTrue(out['model_fallback'])
        self.assertIn('503', out['fallback_reason'])
        records = self.logs()
        self.assertTrue(any(r.get('model_fallback') for r in records))
        self.assertNotIn('gem-key', json.dumps(records))

    def test_gemini_timeout_and_no_channel_fall_back(self):
        def timeout(host, model):
            if host == 'www.micuapi.ai':
                raise httpx.ReadTimeout('slow')
            return ok(model)
        self.assertEqual(self.client(timeout)('compose', MSG, 10)['model'], 'claude-opus-5-5')
        self.seen.clear()

        def no_channel(host, model):
            if host == 'www.micuapi.ai':
                return httpx.Response(503, json={'error': {'code': 'model_not_found', 'message': 'No available channel'}})
            return ok(model)
        self.assertEqual(self.client(no_channel)('compose', MSG, 10)['model'], 'claude-opus-5-5')

    def test_gemini_quota_exhausted_falls_back(self):
        def quota(host, model):
            if host == 'www.micuapi.ai':
                return httpx.Response(403, json={'error': {'code': 'insufficient_user_quota', 'message': '令牌额度不足'}})
            return ok(model)
        out = self.client(quota)('compose', MSG, 10)
        self.assertEqual(out['model'], 'claude-opus-5-5')
        self.assertTrue(out['model_fallback'])

    def test_missing_gemini_key_uses_fallback_without_failing(self):
        c = self.client(lambda host, model: ok(model), env={})
        out = c('compose', MSG, 10)
        self.assertEqual(self.seen, [('api.erisedai.com', 'Bearer default-key', 'claude-opus-5-5')])
        self.assertTrue(out['model_fallback'])
        self.assertIn('GEMINI_RELAY_API_KEY', out['fallback_reason'])

    def test_response_model_mismatch_is_not_a_fallback(self):
        c = self.client(lambda host, model: ok('some-other-model'))
        with self.assertRaises(ValueError):
            c('compose', MSG, 10)
        self.assertEqual(len(self.seen), 1)

    def test_other_stages_stay_on_opus_5(self):
        self.client(lambda host, model: ok(model))('stance', MSG, 10)
        self.assertEqual(self.seen, [('api.erisedai.com', 'Bearer default-key', 'claude-opus-5')])


if __name__ == '__main__':
    unittest.main()


class QuotaBreakerTests(ClientFallbackTests):
    """Oct 6 v9: after one quota answer the stage skips the primary for the rest of the process,
    and the fallback's max_tokens is clamped (it is not a thinking model)."""

    def test_quota_trips_breaker_and_clamps_fallback_tokens(self):
        from live import erisedai_distillation_client as relay

        def quota(host, model):
            if host == 'www.micuapi.ai':
                return httpx.Response(403, json={'error': {'code': 'insufficient_user_quota', 'message': '用户额度不足'}})
            return ok(model)
        client = self.client(quota)
        client('compose', MSG, 12000)
        client('compose', MSG, 12000)
        self.assertEqual([s[2] for s in self.seen], ['gemini-3.1-pro-preview', 'claude-opus-5-5', 'claude-opus-5-5'])
        self.assertIn(('compose', 'gemini-3.1-pro-preview'), relay.quota_tripped())
        fallbacks = [r for r in self.logs() if r['model'] == 'claude-opus-5-5']
        self.assertTrue(all(r['max_tokens'] == relay.FALLBACK_MAX_TOKENS for r in fallbacks))
        self.assertTrue(any('quota breaker open' in r.get('fallback_reason', '') for r in fallbacks))

    def test_timeout_does_not_trip_breaker(self):
        from live import erisedai_distillation_client as relay

        def timeout(host, model):
            if host == 'www.micuapi.ai':
                raise httpx.ReadTimeout('slow')
            return ok(model)
        self.client(timeout)('compose', MSG, 10)
        self.assertEqual(relay.quota_tripped(), {})
