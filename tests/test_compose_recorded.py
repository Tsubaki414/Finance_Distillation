"""P0-4e: real relay EXTRACT + COMPOSE responses (Liberty Street -> zh_macro)
replayed offline. The post-level checks are deterministic over the recorded
responses: data_take, frame present, length in range, no findings, persona
version written, not publishable."""
import json
from pathlib import Path
import unittest

from live import compose
from live.recorded_client import RecordedClient, load_calls

FIXTURE = Path(__file__).parent / 'fixtures' / 'recorded' / 'compose_libertystreet'


class RecordedComposeTests(unittest.TestCase):
    def test_recorded_compose_passes_post_checks(self):
        data = json.loads((FIXTURE / 'input.json').read_text())
        client = RecordedClient(load_calls(FIXTURE / 'calls.jsonl'))
        # Recorded before exemplar retrieval existed: replay the same request.
        result = compose.compose_source(data['source'], data['account_id'], client, exemplars=False)
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
