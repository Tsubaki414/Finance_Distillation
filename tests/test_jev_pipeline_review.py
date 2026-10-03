import copy
import unittest

from scripts.jev_pipeline_review import build_packet


class ReadOnlyStore:
    def __init__(self):
        self.runs = {
            'time': {'id': 'time', 'source_adaptation': {
                'source': {'published_at': '2026-09-30T12:00:00Z', 'text': 'PRIVATE ARTICLE'},
                'attempt': {'account_context': {'as_of': '2026-10-02T12:00:00Z'}},
                'route': {'decision': 'SKIP', 'reason': 'This September article is in the future.'}}},
            'hygiene': {'id': 'hygiene', 'source_adaptation': {'attempt': {
                'hygiene_decisions': [{'annotation_id': 'a1', 'action': 'needs_context',
                                      'reason': 'Independent text; only a private flag is needed.'}]}}},
            'transport': {'id': 'transport', 'source_adaptation': {
                'execution_failure': {'stage': 'translation', 'code': 'content_filter'}}},
        }

    def get(self, kind, key):
        assert kind == 'runs'
        return self.runs[key]


class JevPacketTests(unittest.TestCase):
    def packet(self, store):
        return build_packet(store, {'temporal': 'time', 'hygiene': 'hygiene', 'transport': 'transport'})

    def test_actual_evidence_without_body_or_prefilled_verdict(self):
        store = ReadOnlyStore()
        before = copy.deepcopy(store.runs)
        packet = self.packet(store)
        self.assertEqual(packet['state']['temporal']['computed_publication_order'], 'before_or_equal')
        self.assertEqual(set(packet['questions']), {'temporal_rationale', 'hygiene_rationale'})
        self.assertFalse(packet['deterministic_checks']['transport']['jev_call_needed'])
        self.assertNotIn('PRIVATE ARTICLE', str(packet))
        self.assertNotIn('expected_answers', packet)
        self.assertEqual(store.runs, before)

    def test_dates_computed_in_code_with_timezone(self):
        store = ReadOnlyStore()
        store.runs['time']['source_adaptation']['source']['published_at'] = '2026-10-03T12:00:00Z'
        self.assertEqual(self.packet(store)['state']['temporal']['computed_publication_order'], 'after')
        store.runs['time']['source_adaptation']['source']['published_at'] = '2026-10-03T12:00:00'
        with self.assertRaises(ValueError):
            self.packet(store)

    def test_missing_hygiene_evidence_is_not_fabricated(self):
        store = ReadOnlyStore()
        store.runs['hygiene']['source_adaptation']['attempt']['hygiene_decisions'] = []
        with self.assertRaises(ValueError):
            self.packet(store)


if __name__ == '__main__':
    unittest.main()
