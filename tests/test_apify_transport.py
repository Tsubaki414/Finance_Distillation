import copy
import hashlib
import unittest
from live.apify_distillation_client import response_from
from scripts.apify_passthrough.main import encoded, validate


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.payload = {'model': 'anthropic/claude-opus-5', 'messages': [
            {'role': 'system', 'content': 'Frozen instruction'},
            {'role': 'user', 'content': '中文原文。\nOriginal reasoning & 30%.'}],
            'temperature': 0.0, 'max_tokens': 28000}
        self.output = {'call_id': 'call-1', 'request_sha256': hashlib.sha256(encoded(self.payload)).hexdigest(),
                       'model_call_attempts': 1, 'status': 'completed', 'response': {
                           'model': 'anthropic/claude-opus-5', 'id': 'provider-response',
                           'choices': [{'message': {'content': ' exact translation '}, 'finish_reason': 'stop'}],
                           'usage': {'prompt_tokens': 25, 'completion_tokens': 3}}}

    def test_full_original_parameters_preserved(self):
        before = copy.deepcopy(self.payload)
        self.assertEqual(validate(self.payload), before)
        self.assertEqual(self.payload, before)
        self.assertEqual(self.payload['max_tokens'], 28000)
        out = response_from(self.output, self.payload, 'call-1')
        self.assertEqual(out['text'], 'exact translation')
        self.assertEqual(out['model'], 'claude-opus-5')
        self.assertEqual(out['provider'], 'apify_openrouter')

    def test_response_bound_to_exact_original_request(self):
        self.payload['messages'][1]['content'] += ' changed'
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            response_from(self.output, self.payload, 'call-1')

    def test_no_model_or_hidden_multiattempt_fallback(self):
        for key, value in [('model_call_attempts', 2), ('call_id', 'other')]:
            out = copy.deepcopy(self.output);out[key] = value
            with self.assertRaises(ValueError): response_from(out, self.payload, 'call-1')
        self.output['response']['model'] = 'anthropic/claude-sonnet-5'
        with self.assertRaisesRegex(ValueError, 'model'):
            response_from(self.output, self.payload, 'call-1')

    def test_no_truncation_or_refusal_disguised_as_stop(self):
        self.output['response']['choices'][0].update(finish_reason='length', message={'content': 'partial', 'refusal': 'no'})
        result = response_from(self.output, self.payload, 'call-1')
        self.assertEqual(result['finish_reason'], 'length')
        self.assertEqual(result['refusal'], 'no')

    def test_reject_mutated_contract_before_any_call(self):
        for patch in [{'temperature': .7}, {'max_tokens': True}, {'model': 'openrouter/auto'}, {'tools': []}]:
            with self.assertRaises(ValueError): validate({**self.payload, **patch})


if __name__ == '__main__': unittest.main()
