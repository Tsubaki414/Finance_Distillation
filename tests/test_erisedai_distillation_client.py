"""Offline relay tests; all HTTP traffic is handled by MockTransport."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from live.erisedai_distillation_client import ErisedaiClient, relay_config
from live.writer_backend import ProviderQuotaError
from ml import budget


class ErisedaiClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.secret = 'test-api-key-do-not-log'
        self.config = {'base_url': 'https://relay.example/v1', 'api_key': self.secret,
                       'model': 'claude-opus-5', 'input_usd_per_million': 15.0,
                       'output_usd_per_million': 75.0}
        self.messages = [{'role': 'system', 'content': 'Return JSON.'},
                         {'role': 'user', 'content': '{"source":"source"}'}]
        self.ledger = self.root / 'spend.json'
        self.ledger.write_text(json.dumps({'cap_usd': 2.0, 'spent_usd': 0.0, 'calls': 0}))
        for name, value in [('LEDGER', self.ledger),
                            ('DISTILLATION_RUNS', self.root / 'spend.jsonl')]:
            p = patch.object(budget, name, value)
            p.start()
            self.addCleanup(p.stop)
        prices = budget.PRICES.copy()
        self.addCleanup(lambda: (budget.PRICES.clear(), budget.PRICES.update(prices)))
        # No inline stage table -> shipped v3 table, whose Gemini stages resolve GEMINI_API_KEY at construction.
        # Use a fake value so these tests never depend on (or touch) a real key.
        env = patch.dict('os.environ', {'GEMINI_API_KEY': 'prefix-AQ.fakeTOKEN123'})
        env.start()
        self.addCleanup(env.stop)
        import os
        for k in ('FD_GEMINI_ONLY', 'FD_GEMINI_MODEL'):
            os.environ.pop(k, None)

    def response(self, **overrides):
        return {'id': 'test-response', 'model': 'claude-opus-5',
                'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 5}, **overrides}

    def client(self, handler):
        return ErisedaiClient(self.root / 'calls', configuration=self.config,
                             transport=httpx.MockTransport(handler))

    def log(self):
        return json.loads(next((self.root / 'calls').glob('*.json')).read_text())

    def test_reserves_before_network_and_settles_exact_usage_without_changing_cap(self):
        def handle(request):
            data = json.loads(self.ledger.read_text())
            self.assertGreater(data['spent_usd'], 0)
            self.assertEqual(data['calls'], 1)
            self.assertEqual(request.url, 'https://relay.example/v1/chat/completions')
            self.assertEqual(request.headers['Authorization'], 'Bearer ' + self.secret)
            self.assertEqual(json.loads(request.content), {
                'model': 'claude-opus-5', 'messages': self.messages,
                'max_tokens': 100, 'temperature': 0.0,
                'response_format': {'type': 'json_object'}})
            return httpx.Response(200, json=self.response())

        with patch('live.erisedai_distillation_client.httpx.Client', wraps=httpx.Client) as constructor:
            result = self.client(handle)('routing', self.messages, 100)
        self.assertIs(constructor.call_args.kwargs['trust_env'], False)
        self.assertIs(constructor.call_args.kwargs['follow_redirects'], False)
        self.assertEqual(result['provider'], 'erisedai_relay')
        self.assertEqual(result['response_model'], 'claude-opus-5')
        ledger = json.loads(self.ledger.read_text())
        self.assertEqual(ledger['cap_usd'], 2.0)
        self.assertAlmostEqual(ledger['spent_usd'], .000525)
        log = self.log()
        self.assertEqual(log['messages'], self.messages)
        self.assertEqual(log['response_format'], {'type': 'json_object'})
        self.assertEqual(log['status'], 'completed')
        self.assertEqual(log['model_call_attempts'], 1)
        self.assertNotIn(self.secret, json.dumps(log))

    def test_requested_json_mode_does_not_repair_malformed_model_content(self):
        from live.model_json import parse_object
        malformed = '{"edits":[{"reason":"原文中的"引语"。"}]}'
        response = self.response(choices=[{'message': {'content': malformed}, 'finish_reason': 'stop'}])
        result = self.client(lambda req: httpx.Response(200, json=response))(
            'localization', self.messages, 100)
        self.assertEqual(result['text'], malformed)
        self.assertEqual(self.log()['response']['text'], malformed)
        self.assertEqual(self.log()['response_format'], {'type': 'json_object'})
        with self.assertRaises(json.JSONDecodeError):
            parse_object(result['text'])

    def test_budget_block_makes_zero_requests_and_has_saved_failure(self):
        self.ledger.write_text(json.dumps({'cap_usd': .000001, 'spent_usd': 0.0, 'calls': 0}))
        def handle(request):
            self.fail('Budget-exhausted request must not be sent')
        with self.assertRaises(budget.BudgetExceeded):
            self.client(handle)('routing', self.messages, 100)
        self.assertEqual(self.log()['model_call_attempts'], 0)
        self.assertEqual(self.log()['error_type'], 'BudgetExceeded')

    def test_quota_and_credential_echo_are_redacted_and_not_retried(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(402, json={'error': {'message': 'insufficient quota ' + self.secret,
                                                       'api_key': self.secret}})
        with self.assertRaises(ProviderQuotaError) as caught:
            self.client(handle)('translation', self.messages, 100)
        self.assertNotIn(self.secret, str(caught.exception))
        self.assertNotIn(self.secret, json.dumps(self.log()))
        self.assertEqual(len(requests), 1)
        self.assertGreater(json.loads(self.ledger.read_text())['spent_usd'], 0,
                           'Unknown billing retains its conservative reservation')

    def test_invalid_json_does_not_expose_raw_document(self):
        with self.assertRaises(json.JSONDecodeError) as caught:
            self.client(lambda req: httpx.Response(200, text='{' + self.secret))(
                'translation', self.messages, 100)
        self.assertEqual(caught.exception.doc, '')
        self.assertNotIn(self.secret, json.dumps(self.log()))

    def test_non_json_402_is_quota_failure(self):
        with self.assertRaises(ProviderQuotaError):
            self.client(lambda req: httpx.Response(402, text='balance exhausted'))(
                'translation', self.messages, 100)

    def test_invalid_usage_preserves_log_and_reservation(self):
        with self.assertRaisesRegex(RuntimeError, 'settlement failed'):
            self.client(lambda req: httpx.Response(200, json=self.response(
                usage={'prompt_tokens': -1, 'completion_tokens': 1})))(
                    'translation', self.messages, 100)
        self.assertEqual(self.log()['accounting_error'], 'ValueError')
        self.assertEqual(self.log()['status'], 'failed')
        reservation = next(iter(json.loads(self.ledger.read_text())['reservations'].values()))
        self.assertFalse(reservation['settled'])

    def test_transport_error_is_sanitized_and_bounded(self):
        def handle(request):
            self.assertEqual(request.extensions['timeout']['read'], 180.0)
            raise httpx.ReadTimeout('Echoed ' + self.secret, request=request)
        with self.assertRaisesRegex(RuntimeError, 'ReadTimeout') as caught:
            self.client(handle)('translation', self.messages, 100)
        self.assertNotIn(self.secret, str(caught.exception))
        self.assertEqual(self.log()['error_type'], 'ReadTimeout')

    def test_redirects_and_model_substitution_are_rejected_without_fallback(self):
        for response in [httpx.Response(302, headers={'location': 'https://other.example'}, json={}),
                         httpx.Response(200, json=self.response(model='other-model'))]:
            with self.subTest(status=response.status_code), \
                    self.assertRaises((RuntimeError, ValueError)):
                self.client(lambda req: response)('routing', self.messages, 100)

    def test_finish_and_refusal_reach_existing_pipeline_validation(self):
        for finish, refusal in [('content_filter', None), ('length', None), ('stop', 'refused')]:
            data = self.response(choices=[{'message': {'content': '', 'refusal': refusal},
                                          'finish_reason': finish}])
            result = self.client(lambda req: httpx.Response(200, json=data))(
                'localization', self.messages, 100)
            self.assertEqual(result['finish_reason'], finish)
            self.assertEqual(result['refusal'], refusal)

    def test_explicit_configuration_overrides_local_file_without_other_keys(self):
        with patch('live.erisedai_distillation_client._dotenv', return_value={
            'ACCOUNT_RELAY_BASE_URL': 'https://file.example/v1',
            'ACCOUNT_RELAY_API_KEY': 'file-key', 'WRITER_API_KEY': 'wrong-key'}), \
                patch.dict('os.environ', {'ACCOUNT_RELAY_BASE_URL': 'https://env.example/v1',
                                          'ACCOUNT_RELAY_API_KEY': self.secret}, clear=True):
            config = relay_config()
        self.assertEqual(config['base_url'], 'https://env.example/v1')
        self.assertEqual(config['api_key'], self.secret)
        self.assertEqual(config['input_usd_per_million'], 15)

    def test_existing_review_erisedai_pair_is_used_without_copying_credentials(self):
        with patch('live.erisedai_distillation_client._dotenv', return_value={
            'REVIEW_BASE_URL': 'https://api.erisedai.com/v1/', 'REVIEW_API_KEY': self.secret,
            'WRITER_API_KEY': 'unrelated'}), patch.dict('os.environ', {}, clear=True):
            config = relay_config()
        self.assertEqual(config['base_url'], 'https://api.erisedai.com/v1')
        self.assertEqual(config['api_key'], self.secret)
        self.assertEqual(config['configuration_source'], 'REVIEW')

    def test_partial_account_pair_never_borrows_review_key(self):
        for explicit in ({'ACCOUNT_RELAY_BASE_URL': 'https://other.example/v1'},
                         {'ACCOUNT_RELAY_API_KEY': 'explicit-key'}):
            with self.subTest(explicit=list(explicit)), \
                    patch('live.erisedai_distillation_client._dotenv', return_value={
                        **explicit, 'REVIEW_BASE_URL': 'https://api.erisedai.com/v1',
                        'REVIEW_API_KEY': self.secret}), patch.dict('os.environ', {}, clear=True), \
                    self.assertRaisesRegex(ValueError, 'configured together'):
                relay_config()

    def test_review_alias_cannot_send_key_to_an_unrelated_provider(self):
        with patch('live.erisedai_distillation_client._dotenv', return_value={
            'REVIEW_BASE_URL': 'https://unrelated.example/v1', 'REVIEW_API_KEY': self.secret}), \
                patch.dict('os.environ', {}, clear=True), self.assertRaisesRegex(ValueError, 'erisedai host'):
            relay_config()

    def test_config_rejects_unsafe_url_and_rates(self):
        for url in ['http://relay.example/v1', 'https://key@relay.example/v1',
                    'https://relay.example/v1?api_key=secret', 'https://relay.example/v1#secret']:
            with self.subTest(url=url), patch('live.erisedai_distillation_client._dotenv', return_value={}), \
                    patch.dict('os.environ', {'ACCOUNT_RELAY_BASE_URL': url}, clear=True), \
                    self.assertRaises(ValueError):
                relay_config()
        with patch('live.erisedai_distillation_client._dotenv', return_value={}), \
                patch.dict('os.environ', {'ACCOUNT_RELAY_BASE_URL': 'https://relay.example/v1',
                                          'ACCOUNT_RELAY_INPUT_USD_PER_MILLION': 'nan'}, clear=True), \
                self.assertRaises(ValueError):
            relay_config()


if __name__ == '__main__':
    unittest.main()
