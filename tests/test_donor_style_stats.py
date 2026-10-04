"""Per-persona style stats derived from deep-scraped donor posts + tags (data-derived portraits)."""
import unittest

from live import donor_style


def post(i, text, **kw):
    return {'id': str(i), 'text': text, 'rt': False, 'reply': False, 'self_thread': False, 'pinned': False,
            'media': [], 'is_note': False, **kw}


class StyleStatsTests(unittest.TestCase):
    def test_originals_exclude_retweets_replies_and_pinned(self):
        posts = [post(1, 'a'), post(2, 'b', rt=True), post(3, 'c', reply=True), post(4, 'd', pinned=True), post(5, 'e', self_thread=True)]
        self.assertEqual([p['id'] for p in donor_style.originals(posts)], ['1', '5'])

    def test_aggregate_shares_and_percentiles(self):
        tags = {'1': {'post_type': 'data_take', 'hook': 'data_point', 'numbers': 4, 'structure': {'chars': 100, 'list': False, 'thread_marker': False, 'question_open': False, 'has_link': True}, 'jev_fallback': False},
                '2': {'post_type': 'hot_take', 'hook': 'bold_claim', 'numbers': 0, 'structure': {'chars': 300, 'list': True, 'thread_marker': False, 'question_open': True, 'has_link': False}, 'jev_fallback': False}}
        s = donor_style.aggregate([tags['1'], tags['2']])
        self.assertEqual(s['posts'], 2)
        self.assertEqual(s['post_type_mix'], {'data_take': 0.5, 'hot_take': 0.5})
        self.assertEqual(s['hook_mix'], {'data_point': 0.5, 'bold_claim': 0.5})
        self.assertEqual(s['median_chars'], 200)
        self.assertEqual(s['share_3plus_numbers'], 0.5)
        self.assertEqual(s['list_share'], 0.5)
        self.assertEqual(s['jev_tagged_share'], 1.0)

    def test_weighted_cluster_stats_use_donor_weights(self):
        per_donor = {'a': donor_style.aggregate([{'post_type': 'data_take', 'hook': 'data_point', 'numbers': 3, 'structure': {'chars': 100}, 'jev_fallback': True}]),
                     'b': donor_style.aggregate([{'post_type': 'hot_take', 'hook': 'question', 'numbers': 0, 'structure': {'chars': 300}, 'jev_fallback': True}])}
        c = donor_style.cluster(per_donor, {'a': 0.75, 'b': 0.25})
        self.assertAlmostEqual(c['post_type_mix']['data_take'], 0.75)
        self.assertAlmostEqual(c['numbers_per_post'], 2.25)


if __name__ == '__main__':
    unittest.main()
