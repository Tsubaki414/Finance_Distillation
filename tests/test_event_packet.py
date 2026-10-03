"""Hormuz fixture regression for EVENT → retrieval → packet → angle.

No network, no model, no persona. The fixture is the 2026-09-27 research
round, frozen in live/research/hormuz_20260926.json.

Run: .venv/bin/python -B -m unittest tests.test_event_packet
"""
from pathlib import Path
import sys, unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))

import event_packet as ep


class HormuzChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = ep.load_fixture()
        cls.result = ep.run(cls.raw['items'])

    def test_one_event_not_one_article(self):
        members = self.result['event']['member_ids']
        self.assertIn('gn-france24', members)
        self.assertIn('bbc-body', members)
        self.assertIn('gn-cls-friday', members)
        self.assertGreaterEqual(len(members), 6)
        self.assertEqual(self.result['event']['independent_families'].count('bbc'), 1)

    def test_related_wording_dispute_stays_out(self):
        excluded = {row['id']: row['why'] for row in self.result['event']['excluded']}
        self.assertEqual(excluded.get('x-qinbafrank'), 'related_or_off_event')
        self.assertIn('x-qinbafrank', self.result['retrieval']['related_separate_events'])
        self.assertNotIn('x-qinbafrank', self.result['event']['member_ids'])

    def test_off_event_posts_stay_out(self):
        excluded = {row['id'] for row in self.result['event']['excluded']}
        self.assertIn('x-deltaone-cuba', excluded)
        self.assertIn('x-andurand-offtopic', excluded)
        self.assertTrue(self.result['retrieval']['specialist_empty'])

    def test_hotness_opens_a_packet(self):
        self.assertGreaterEqual(self.result['hotness']['score'], 60)
        self.assertTrue(self.result['hotness']['open_packet'])

    def test_retrieval_quota(self):
        retrieval = self.result['retrieval']
        # BBC is major reporting. The official slot stays empty.
        self.assertEqual(retrieval['primary_official'], [])
        self.assertIn('bbc-body', retrieval['wire_major'])
        self.assertNotIn('bbc-body', retrieval['primary_official'])
        self.assertGreaterEqual(len(retrieval['analysis']), 1)
        self.assertLessEqual(len(retrieval['analysis']), 5)
        self.assertIn('wx-yicai', retrieval['analysis'])
        self.assertIn('gn-wsj', retrieval['wire_major'])
        self.assertEqual(retrieval['specialist'], [])
        self.assertEqual(retrieval['basis'], 'single_major_attributed')

    def test_packet_keeps_fact_confidence(self):
        packet = self.result['packet']
        numbers = {f['fact_id']: f for f in packet['important_numbers']}
        self.assertEqual(numbers['f-wti']['value'], 92.41)
        self.assertEqual(numbers['f-brent']['value'], 104.32)
        self.assertEqual(numbers['f-wti']['confidence'], 'reported_settlement')
        self.assertNotEqual(numbers['f-wti']['confidence'], 'exchange_tape')
        self.assertEqual(numbers['f-wti']['admission'], 'single_major_attributed')
        by_id = {f['fact_id']: f for f in packet['primary_facts']}
        self.assertIn('f-oral-reject', by_id)
        self.assertIn('f-await-official', by_id)
        self.assertIn('f-fifth', by_id)
        self.assertEqual(by_id['f-oral-reject']['tier'], 'WIRE_MAJOR')
        self.assertEqual(by_id['f-oral-reject']['admission'], 'single_major_attributed')
        self.assertEqual(packet['admission']['official_count'], 0)
        self.assertEqual(packet['admission']['basis'], 'single_major_attributed')

    def test_headline_only_claim_is_not_a_fact(self):
        packet = self.result['packet']
        fact_text = ' '.join(f['text'] for f in packet['primary_facts'])
        self.assertNotIn('midterm', fact_text.lower())
        self.assertTrue(any('WSJ' in u for u in packet['unknown']))
        self.assertTrue(any(r['phrase'] == '纳指涨逾2%' for r in packet['refused_claims']))

    def test_ledger_points_at_sources(self):
        ledger = self.result['packet']['ledger']
        by_claim = {row['claim_id']: row for row in ledger}
        self.assertEqual(by_claim['f-wti']['source_id'], 'wire-friday-settle')
        self.assertEqual(by_claim['f-oral-reject']['source_id'], 'bbc-body')
        self.assertEqual(by_claim['f-oral-reject']['tier'], 'WIRE_MAJOR')
        self.assertEqual(by_claim['f-oral-reject']['admission'], 'single_major_attributed')
        self.assertEqual(by_claim['f-oral-reject']['url'],
                         'https://www.bbc.com/news/articles/cmvgyyw2jeego')
        self.assertFalse(by_claim['view:gn-wsj']['body_read'])

    def test_timestamps_leave_unread_gaps_open(self):
        ts = self.result['packet']['timestamps']
        self.assertEqual(ts['event_first_seen'], '2026-09-26T02:06:07+00:00')
        self.assertEqual(ts['first_seen_kind'], 'google_news_index')
        self.assertIsNone(ts['first_quality_source'])
        self.assertIsNone(ts['first_official_confirmation'])
        self.assertEqual(ts['first_wire_major_body'], '2026-09-27T02:16:52+00:00')
        self.assertEqual(ts['second_source_arrival'], '2026-09-26T03:45:17+00:00')
        lags = ts['lags']
        self.assertIsNone(lags['detection_lag']['seconds'])
        self.assertEqual(lags['detection_lag']['status'], 'open')
        self.assertIsNone(lags['total_reaction_lag']['seconds'])
        self.assertIsNotNone(lags['research_lag']['seconds'])
        self.assertGreater(lags['research_lag']['seconds'], 20 * 3600)

    def test_angle_is_the_expectation_gap(self):
        # One BBC body is enough to write, and only with BBC named. It is
        # not two independent majors and it is not an official document.
        angle = self.result['angle']
        self.assertEqual(angle['angle_id'], 'expectation_gap')
        self.assertTrue(angle['publish'])
        self.assertEqual(angle['attribution'], 'single_source')
        self.assertIn('Monday oil will gap up', angle['must_not_assert'])
        rejected = {row['id'] for row in angle['rejected']}
        self.assertIn('oil_must_gap', rejected)
        self.assertIn('x-qinbafrank', angle['related_event_ids'])

    def test_selector_refuses_when_primary_body_is_missing(self):
        items = [x for x in self.raw['items'] if x['id'] != 'bbc-body']
        result = ep.run(items)
        self.assertEqual(result['retrieval']['primary_official'], [])
        self.assertNotIn('bbc-body', result['retrieval']['wire_major'])
        self.assertEqual(result['retrieval']['basis'], 'no_body')
        self.assertNotEqual(result['angle'].get('angle_id'), 'expectation_gap')
        self.assertFalse(result['angle'].get('publish'))


if __name__ == '__main__':
    unittest.main()
