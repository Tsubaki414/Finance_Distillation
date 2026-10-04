"""Narrow Jev judgments for the pipeline front end (J2/J3-style, advisory):
source routing per persona, content-unit pre-screen, donor-post tagging.
Every Jev failure falls back and records jev_fallback=True (task card rule 5)."""
import unittest

from live import jev_front as jf


class FakeJev:
    def __init__(self, pick, status='completed'):
        self.pick, self.status, self.calls = pick, status, []

    def review(self, state, questions):
        self.calls.append((state, questions))
        if self.status != 'completed':
            return {'status': self.status, 'answers': {}}
        return {'status': 'completed', 'answers': {q: {'choice': self.pick(q, spec), 'confidence': 0.9,
                                                       'probabilities': {}} for q, spec in questions.items()}}


ITEMS = [{'id': f's{i}', 'title': t, 'publisher': 'Fed', 'snippet': ''} for i, t in
         enumerate(['FOMC statement holds rates', 'Bitcoin ETF flows hit record', 'Micron raises HBM guidance'])]


class RoutingTests(unittest.TestCase):
    def test_route_uses_jev_choice_per_item_and_batches(self):
        picks = {'s0': 'macro_rates_en', 's1': 'crypto_macro_en', 's2': 'industry_ai_capex'}
        jev = FakeJev(lambda q, spec: picks[q])
        out = jf.route_sources(ITEMS * 6, jev=jev)  # 18 items -> 2 calls (<=16 questions each)
        self.assertEqual(len(jev.calls), 2)
        self.assertEqual(out['s0']['persona'], 'macro_rates_en')
        self.assertFalse(out['s0']['jev_fallback'])
        labels = set(next(iter(jev.calls[0][1].values()))['criteria'])
        self.assertEqual(labels, set(jf.PERSONAS) | {'none'})

    def test_route_falls_back_to_keywords_and_flags_it(self):
        out = jf.route_sources(ITEMS, jev=FakeJev(None, status='failed'))
        self.assertTrue(all(v['jev_fallback'] for v in out.values()))
        self.assertEqual(out['s1']['persona'], 'crypto_macro_en')


class PrescreenTests(unittest.TestCase):
    def test_units_get_keep_weak_drop(self):
        units = [{'unit_id': 'u1', 'statement': 'Unemployment rose to 4.2% in September.', 'kind': 'fact'},
                 {'unit_id': 'u2', 'statement': 'See page 3 for disclosures.', 'kind': 'fact'}]
        jev = FakeJev(lambda q, spec: 'keep' if q == 'u1' else 'drop')
        out = jf.prescreen_units(units, persona='macro_rates_en', jev=jev)
        self.assertEqual({k: v['verdict'] for k, v in out.items()}, {'u1': 'keep', 'u2': 'drop'})

    def test_prescreen_fallback_keeps_everything_flagged(self):
        out = jf.prescreen_units([{'unit_id': 'u1', 'statement': 'x', 'kind': 'fact'}], persona='macro_zh',
                                 jev=FakeJev(None, status='failed'))
        self.assertEqual(out['u1'], {'verdict': 'keep', 'jev_fallback': True, 'confidence': None})


class TaggingTests(unittest.TestCase):
    def test_posts_get_post_type_and_hook_plus_deterministic_features(self):
        posts = [{'id': '1', 'text': 'CPI rose 0.4% in August, above the 0.3% consensus. Core was 3.1% y/y.'}]
        jev = FakeJev(lambda q, spec: 'data_take' if q.endswith(':post_type') else 'data_point')
        out = jf.tag_posts(posts, jev=jev)
        tag = out['1']
        self.assertEqual((tag['post_type'], tag['hook']), ('data_take', 'data_point'))
        self.assertEqual(tag['numbers'], 3)
        self.assertFalse(tag['jev_fallback'])
        self.assertIn('structure', tag)

    def test_tag_fallback_uses_rules(self):
        out = jf.tag_posts([{'id': '1', 'text': 'Why does the curve invert? Because ' + 'x ' * 300}], jev=None)
        self.assertTrue(out['1']['jev_fallback'])
        self.assertEqual(out['1']['post_type'], 'mechanism_explainer')


if __name__ == '__main__':
    unittest.main()
