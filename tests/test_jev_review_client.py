"""Offline TypeSafe contract tests; no real Jev advice or production effects."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from live.jev_review_client import BUDGET_MODEL, ENDPOINT, MODEL, JevReviewClient
from ml import budget


class JevReviewClientTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.key = 'synthetic-typesafe-secret-never-log'
        self.state = {'case': 'synthetic failure', 'execution_success': False}
        self.questions = {'next_check': {'type': 'choice', 'instructions': 'Suggest a private next check.',
            'criteria': {'inspect_contract': 'Inspect typed response contract.',
                         'human_review': 'Ask an editor to assess the conflicting decision.'}}}
        self.ledger = self.root / 'spend.json'
        self.ledger.write_text(json.dumps({'cap_usd': 100.0, 'spent_usd': 2.0, 'calls': 3}))
        for name, value in [('LEDGER', self.ledger), ('DISTILLATION_RUNS', self.root / 'spend.jsonl')]:
            patched = patch.object(budget, name, value)
            patched.start()
            self.addCleanup(patched.stop)

    def response(self):
        return {'model': MODEL, 'answers': {'next_check': {'type': 'choice', 'choice': 'inspect_contract',
            'probabilities': {'inspect_contract': 0.7, 'human_review': 0.3}, 'confidence': 0.9}},
                'usage': {'input_tokens': 500, 'output_tokens': 0}}

    def client(self, handler, **kwargs):
        return JevReviewClient(self.root / 'calls', api_key=kwargs.get('api_key', self.key),
                               transport=httpx.MockTransport(handler))

    def log(self, result):
        return json.loads(Path(result['log_path']).read_text())

    def reservation(self, result):
        return json.loads(self.ledger.read_text())['reservations'][result['call_id']]

    def no_network(self, request):
        self.fail('Preflight must not send a request')

    def test_success_fixed_endpoint_reserves_before_network_and_remains_advisory(self):
        received = []
        original_state, original_questions = copy.deepcopy(self.state), copy.deepcopy(self.questions)
        def handle(request):
            received.append(request)
            ledger = json.loads(self.ledger.read_text())
            self.assertEqual(ledger['calls'], 4)
            self.assertGreater(ledger['spent_usd'], 2)
            started_log = json.loads(next((self.root / 'calls').glob('*.json')).read_text())
            self.assertEqual(started_log['status'], 'started')
            self.assertEqual(started_log['model_call_attempts'], 1)
            self.assertEqual(str(request.url), ENDPOINT)
            self.assertEqual(request.headers['Authorization'], 'Bearer ' + self.key)
            self.assertEqual(request.extensions['timeout']['read'], 30.0)
            self.assertEqual(json.loads(request.content), {
                'model': MODEL, 'state': self.state, 'questions': self.questions})
            return httpx.Response(200, json=self.response())
        with patch('live.jev_review_client.httpx.Client', wraps=httpx.Client) as constructor:
            result = self.client(handle).review(self.state, self.questions)
        self.assertEqual(result['status'], 'completed')
        self.assertIsNone(result['error_code'])
        self.assertTrue(result['advisory_only'])
        self.assertTrue(result['human_review_required'])
        self.assertFalse(result['execution_authorized'])
        self.assertEqual(result['answers'], self.response()['answers'])
        self.assertFalse(constructor.call_args.kwargs['trust_env'])
        self.assertFalse(constructor.call_args.kwargs['follow_redirects'])
        self.assertEqual(len(received), 1)
        self.assertEqual(self.state, original_state)
        self.assertEqual(self.questions, original_questions)
        self.assertEqual(budget.price_of(BUDGET_MODEL), (0.042, 0.0))
        self.assertAlmostEqual(json.loads(self.ledger.read_text())['spent_usd'], 2.000021)
        self.assertEqual(json.loads(self.ledger.read_text())['cap_usd'], 100.0)
        self.assertTrue(self.reservation(result)['settled'])
        log = self.log(result)
        self.assertEqual(log['response'], self.response())
        self.assertEqual(log['request']['state'], self.state)
        self.assertNotIn(self.key, json.dumps(log))
        self.assertNotIn('Authorization', json.dumps(log))

    def test_missing_key_logs_block_without_budget_or_network(self):
        previous = self.ledger.read_bytes()
        result = self.client(self.no_network, api_key='').review(self.state, self.questions)
        self.assertEqual((result['status'], result['error_code']), ('blocked', 'missing_api_key'))
        self.assertEqual(self.ledger.read_bytes(), previous)
        self.assertEqual(self.log(result)['model_call_attempts'], 0)
        self.assertEqual(self.log(result)['accounting_status'], 'not_reserved')

    def test_credential_precedence_never_borrows_other_provider_keys(self):
        with patch('live.jev_review_client._dotenv', return_value={
            'TYPESAFE_API_KEY': 'file-specific', 'REVIEW_API_KEY': 'wrong-relay',
            'OPENROUTER_API_KEY': 'wrong-openrouter'}), patch.dict('os.environ', {}, clear=True):
            self.assertEqual(JevReviewClient(self.root)._api_key, 'file-specific')
            with patch.dict('os.environ', {'TYPESAFE_API_KEY': 'shell-specific'}):
                self.assertEqual(JevReviewClient(self.root)._api_key, 'shell-specific')
                self.assertEqual(JevReviewClient(self.root, api_key='explicit')._api_key, 'explicit')
            with patch.dict('os.environ', {'TYPESAFE_API_KEY': ''}):
                self.assertEqual(JevReviewClient(self.root)._api_key, '')
        with patch('live.jev_review_client._dotenv', return_value={'REVIEW_API_KEY': 'wrong-relay'}), \
                patch.dict('os.environ', {}, clear=True):
            self.assertEqual(JevReviewClient(self.root)._api_key, '')

    def test_budget_exceeded_never_sends_or_changes_ledger(self):
        self.ledger.write_text(json.dumps({'cap_usd': 100.0, 'spent_usd': 100.0, 'calls': 3}))
        previous = self.ledger.read_bytes()
        result = self.client(self.no_network).review(self.state, self.questions)
        self.assertEqual(result['error_code'], 'budget_exceeded')
        self.assertEqual(self.ledger.read_bytes(), previous)
        self.assertEqual(self.log(result)['model_call_attempts'], 0)

    def test_invalid_requests_stop_before_network_and_reservation(self):
        cases = [([], self.questions), ({'bad': float('nan')}, self.questions),
                 ({1: 'non-string key'}, self.questions), ({'bad': object()}, self.questions),
                 (self.state, {}), (self.state, {str(i): self.questions['next_check'] for i in range(17)}),
                 ({'large': '汉' * 12000}, self.questions),
                 (self.state, {'q': {**self.questions['next_check'], 'type': 'score'}}),
                 (self.state, {'q': {**self.questions['next_check'], 'unknown': True}}),
                 (self.state, {'q': {**self.questions['next_check'], 'criteria': {}}}),
                 (self.state, {'q': {**self.questions['next_check'], 'criteria': {'x': ''}}})]
        previous = self.ledger.read_bytes()
        for state, questions in cases:
            with self.subTest(state_type=type(state).__name__, questions=len(questions)):
                result = self.client(self.no_network).review(state, questions)
                self.assertEqual(result['error_code'], 'invalid_request')
                self.assertEqual(self.ledger.read_bytes(), previous)
                self.assertIsNone(self.log(result)['request'])

    def test_key_in_advisory_state_is_not_sent_or_logged(self):
        result = self.client(self.no_network).review({'text': self.key, 'authorization': 'Bearer other-secret'},
                                                   self.questions)
        self.assertEqual(result['error_code'], 'credential_in_request')
        log = json.dumps(self.log(result))
        self.assertNotIn(self.key, log)
        self.assertNotIn('other-secret', log)
        self.assertEqual(self.log(result)['model_call_attempts'], 0)

    def test_criteria_count_bounds_are_two_through_255(self):
        previous = self.ledger.read_bytes()
        for count in (0, 1, 256):
            with self.subTest(count=count):
                questions = {'q': {'type': 'choice', 'instructions': 'Choose one option.',
                                  'criteria': {str(i): 'Synthetic option.' for i in range(count)}}}
                result = self.client(self.no_network).review(self.state, questions)
                self.assertEqual(result['error_code'], 'invalid_request')
                self.assertEqual(self.ledger.read_bytes(), previous)
        for count in (2, 255):
            with self.subTest(count=count):
                questions = {'q': {'type': 'choice', 'instructions': 'Choose one option.',
                                  'criteria': {str(i): 'Synthetic option.' for i in range(count)}}}
                # Missing credentials proves successful local contract validation,
                # without calling the network or changing even the mock ledger.
                result = self.client(self.no_network, api_key='').review(self.state, questions)
                self.assertEqual(result['error_code'], 'missing_api_key')
                self.assertEqual(self.ledger.read_bytes(), previous)

    def test_choice_must_match_maximum_probability_with_ties_allowed(self):
        for probabilities, choice, accepted in [
            ({'inspect_contract': 0.7, 'human_review': 0.3}, 'human_review', False),
            ({'inspect_contract': 0.5, 'human_review': 0.5}, 'human_review', True),
            ({'inspect_contract': 0.5, 'human_review': 0.5}, 'inspect_contract', True),
        ]:
            data = self.response()
            data['answers']['next_check'].update(probabilities=probabilities, choice=choice)
            with self.subTest(choice=choice, probabilities=probabilities):
                result = self.client(lambda request: httpx.Response(200, json=data)).review(
                    self.state, self.questions)
                if accepted:
                    self.assertEqual(result['status'], 'completed')
                    self.assertEqual(result['answers']['next_check']['choice'], choice)
                    self.assertTrue(result['human_review_required'])
                else:
                    self.assertEqual(result['error_code'], 'response_contract')
                    self.assertEqual(result['answers'], {})

    def test_http_failures_do_not_log_error_body_follow_redirect_or_retry(self):
        for status, code in [(401, 'http_unauthorized'), (403, 'http_forbidden'),
                             (402, 'provider_balance'), (429, 'http_rate_limited'),
                             (500, 'http_error'), (302, 'http_error')]:
            sent = []
            def handle(request):
                sent.append(request)
                return httpx.Response(status, text='PRIVATE ' + self.key,
                                      headers={'location': 'https://untrusted.example/'})
            with self.subTest(status=status):
                result = self.client(handle).review(self.state, self.questions)
                self.assertEqual(result['error_code'], code)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['answers'], {})
                self.assertEqual(len(sent), 1)
                self.assertNotIn(self.key, json.dumps(self.log(result)))
                self.assertNotIn('PRIVATE', json.dumps(self.log(result)))
                self.assertGreater(self.reservation(result)['cost'], 0)
                self.assertEqual(self.log(result)['accounting_status'], 'settled_reservation_estimate')

    def test_json_is_never_repaired_and_invalid_documents_not_logged(self):
        bodies = ['{PRIVATE' + self.key, '```json\n{}\n```', '{"model":"x","model":"y"}',
                  '{"value": NaN}', '{"value": Infinity}']
        for body in bodies:
            with self.subTest(body_start=body[:8]):
                result = self.client(lambda request: httpx.Response(200, text=body)).review(
                    self.state, self.questions)
                self.assertEqual(result['error_code'], 'invalid_json')
                self.assertNotIn(self.key, json.dumps(self.log(result)))
                self.assertNotIn('response', self.log(result))
                self.assertGreater(self.reservation(result)['cost'], 0)

    def test_strict_response_keys_model_labels_and_probabilities(self):
        changes = [lambda d: d.update(model='substituted-model'),
                   lambda d: d.update(extra=True),
                   lambda d: d['answers'].update(unrequested=d['answers']['next_check']),
                   lambda d: d['answers'].clear(),
                   lambda d: d['answers']['next_check'].update(type='score'),
                   lambda d: d['answers']['next_check'].update(extra='value'),
                   lambda d: d['answers']['next_check'].update(choice='unknown'),
                   lambda d: d['answers']['next_check'].update(confidence=True),
                   lambda d: d['answers']['next_check'].update(confidence=1.01),
                   lambda d: d['answers']['next_check'].update(probabilities={'inspect_contract': 1}),
                   lambda d: d['answers']['next_check']['probabilities'].update(inspect_contract=0.8),
                   lambda d: d['answers']['next_check']['probabilities'].update(inspect_contract=True),
                   lambda d: d['answers']['next_check']['probabilities'].update(inspect_contract=-0.1)]
        for change in changes:
            data = self.response()
            change(data)
            with self.subTest(response=data):
                result = self.client(lambda request: httpx.Response(200, json=data)).review(
                    self.state, self.questions)
                self.assertEqual(result['error_code'], 'response_contract')
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['answers'], {})
                self.assertNotIn('response', self.log(result))
                self.assertEqual(self.log(result)['accounting_status'], 'settled_reservation_estimate')

    def test_invalid_or_missing_usage_retains_unsettled_reservation(self):
        for usage in (None, {}, {'input_tokens': -1, 'output_tokens': 0},
                      {'input_tokens': True, 'output_tokens': 0},
                      {'input_tokens': 2.5, 'output_tokens': 0},
                      {'input_tokens': 5, 'output_tokens': 0, 'extra': 2}):
            data = self.response()
            data['usage'] = usage
            with self.subTest(usage=usage), patch.object(budget, 'settle', wraps=budget.settle) as settle:
                result = self.client(lambda request: httpx.Response(200, json=data)).review(
                    self.state, self.questions)
                self.assertEqual(result['error_code'], 'usage_contract')
                settle.assert_not_called()
                self.assertFalse(self.reservation(result)['settled'])
                self.assertGreater(self.reservation(result)['estimate'], 0)
                self.assertEqual(self.log(result)['accounting_status'], 'reservation_retained_invalid_usage')

    def test_timeout_keeps_reservation_and_logs_only_error_type(self):
        def handle(request):
            raise httpx.ReadTimeout('Secret ' + self.key, request=request)
        result = self.client(handle).review(self.state, self.questions)
        self.assertEqual(result['error_code'], 'transport_error')
        self.assertEqual(self.log(result)['error_type'], 'ReadTimeout')
        self.assertNotIn(self.key, json.dumps(self.log(result)))
        self.assertGreater(self.reservation(result)['cost'], 0)

    def test_settlement_failure_never_reports_success_or_leaks_exception(self):
        with patch.object(budget, 'settle', side_effect=RuntimeError(self.key)):
            result = self.client(lambda request: httpx.Response(200, json=self.response())).review(
                self.state, self.questions)
        self.assertEqual((result['status'], result['error_code']), ('failed', 'accounting_error'))
        self.assertEqual(result['answers'], {})
        self.assertFalse(self.reservation(result)['settled'])
        self.assertNotIn(self.key, json.dumps(self.log(result)))


if __name__ == '__main__':
    unittest.main()
