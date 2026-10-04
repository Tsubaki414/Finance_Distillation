"""P0-4e: real relay EXTRACT + COMPOSE responses (Liberty Street -> zh_macro)
replayed offline. The post-level checks are deterministic over the recorded
responses: data_take, frame present, length in range, no findings, persona
version written, not publishable."""
import json
from pathlib import Path
import unittest
from dataclasses import replace
import copy
from unittest.mock import patch

from live import compose, registry
from live.recorded_client import RecordedClient, load_calls

FIXTURE = Path(__file__).parent / 'fixtures' / 'recorded' / 'compose_libertystreet'


class RecordedComposeTests(unittest.TestCase):
    def test_recorded_compose_passes_post_checks(self):
        data = json.loads((FIXTURE / 'input.json').read_text())
        client = RecordedClient(load_calls(FIXTURE / 'calls.jsonl'))
        def historical_client(stage, messages, max_tokens):
            # The old recording lacks freshness metadata. Verify every other
            # payload field against its exact recorded hash.
            messages = copy.deepcopy(messages)
            if stage == 'compose':
                payload = json.loads(messages[-1]['content'])
                payload.pop('avoid_patterns', None)   # added after the recording
                for unit in payload['units']:
                    for key in ('historical', 'as_of', 'published_at'):
                        unit.pop(key, None)
                messages[-1]['content'] = json.dumps(payload, ensure_ascii=False)
            return client(stage, messages, max_tokens)

        # Replay the historical persona configuration: this recording predates
        # voice cards, exemplars, and relaxed view prompts. Keep the exact
        # request hash and all checks using the saved historical templates.
        historical_persona = replace(registry.persona_for_account(data['account_id']), voice_card={})
        with patch('live.compose.registry.persona_for_account', return_value=historical_persona), patch('live.compose.COMPOSE', (FIXTURE / 'compose_prompt.txt').read_text()), patch('live.content_units.EXTRACT', (FIXTURE / 'extract_prompt.txt').read_text()):
            result = compose.compose_source(data['source'], data['account_id'], historical_client, exemplars=False, post_type='data_take')
        self.assertEqual(client.used, ['extract', 'compose'])
        self.assertEqual(result['post_type'], 'data_take')
        self.assertEqual(result['post_checks'], [])
        self.assertTrue(result['text'].startswith('Liberty Street Economics：'))
        self.assertTrue(150 <= result['length'] <= 400)
        self.assertEqual(result['persona'], {'persona_id': 'zh_macro', 'version': '1'})
        self.assertFalse(result['publishable'])
        units = {u['unit_id'] for u in result['units']}
        self.assertTrue(all(row['unit_id'] in units for row in result['claim_ledger']))


if __name__ == '__main__':
    unittest.main()
