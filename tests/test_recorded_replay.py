"""P0-4 prerequisite (plan 1.3 subset): offline replay from recorded responses.

The fixture is a real relay run (Morris archive, recovered by P0-3b). Replay
matches each request by (stage, replay key: exact messages minus wall-clock
stamps); an unrecorded or changed
request is an error, so prompt drift is caught instead of silently re-billed.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from live.recorded_client import RecordedClient, UnrecordedCall, load_calls
from live.account_source_adaptation import adapt_source
from live.content_stages import ContentStages

FIXTURE = Path(__file__).parent / 'fixtures' / 'recorded' / 'morris_e6f7'


def replay(fixture=FIXTURE, mutate=None):
    data = json.loads((fixture / 'input.json').read_text())
    source = copy.deepcopy(data['source'])
    if mutate:
        mutate(source)
    client = RecordedClient(load_calls(fixture / 'calls.jsonl'))
    with tempfile.TemporaryDirectory() as tmp:
        result = adapt_source(source, data['account_id'], Path(tmp),
                              ContentStages(Path(tmp) / 'calls', client=client))
    return result, client


class RecordedReplayTests(unittest.TestCase):
    def test_replay_reaches_recorded_outcome_without_network(self):
        result, client = replay()
        self.assertEqual(result['draft_status'], 'draft_ready')
        self.assertEqual(client.used, ['routing', 'evergreen_gate', 'translation', 'localization', 'qa'])
        expected = (FIXTURE / 'expected_final_draft.txt').read_text()
        self.assertEqual(result['final_draft'], expected)

    def test_replay_is_deterministic(self):
        a, _ = replay()
        b, _ = replay()
        self.assertEqual(a['final_draft'], b['final_draft'])

    def test_changed_prompt_is_an_unrecorded_call(self):
        def mutate(source):
            source['title'] = source['title'] + ' (edited)'
        client = RecordedClient(load_calls(FIXTURE / 'calls.jsonl'))
        with self.assertRaises(UnrecordedCall):
            client('routing', [{'role': 'user', 'content': 'not recorded'}], 10)
        result, client = replay(mutate=mutate)
        self.assertNotEqual(result['draft_status'], 'draft_ready')
        self.assertEqual((result.get('execution_failure') or {}).get('error_type'), 'UnrecordedCall')
        self.assertTrue(client.misses)


if __name__ == '__main__':
    unittest.main()


class ReplayKeyTests(unittest.TestCase):
    def test_only_wall_clock_stamps_are_ignored(self):
        from live.recorded_client import replay_key
        base = [{'role': 'user', 'content': json.dumps({'as_of': 't1', 'source': {'snapshot_at': 't1', 'text': 'a'}})}]
        same = [{'role': 'user', 'content': json.dumps({'as_of': 't2', 'source': {'snapshot_at': 't2', 'text': 'a'}})}]
        diff = [{'role': 'user', 'content': json.dumps({'as_of': 't1', 'source': {'snapshot_at': 't1', 'text': 'b'}})}]
        self.assertEqual(replay_key(base), replay_key(same))
        self.assertNotEqual(replay_key(base), replay_key(diff))
