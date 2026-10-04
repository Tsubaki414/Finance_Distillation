"""Shared content store: units with licence tier + attribution, dedup by unit_id,
queryable per persona (seed of the shared insights DB)."""
import tempfile
import unittest

from live import content_store as cs
from live.adapters import common


def source(text='Payrolls rose 22,000 in September 2026.'):
    return common.make_source(id='src-1', source_id='primary_bls', text=text, publisher='U.S. Bureau of Labor Statistics',
                              title='Employment Situation', url='https://www.bls.gov/x', published_at='2026-10-02',
                              adapter='bls_api')


def unit(src, tier='A'):
    from live import content_units as cu
    raw = {'kind': 'fact', 'statement': 'Payrolls rose 22,000.', 'source_spans': [{'paragraph_id': 'P1', 'exact_text': src['original_text']}],
           'numbers': [{'text': '22,000', 'metric': 'payrolls', 'period': 'September 2026', 'span_ref': 0}],
           'speaker': 'BLS', 'speaker_type': 'official', 'freshness_class': 'current'}
    return cu.validate_units_partial(src, {'units': [raw]}, tier)[0][0]


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = cs.ContentStore(tempfile.mkdtemp())
        self.src = source()

    def test_add_dedup_and_query_by_persona(self):
        u = unit(self.src)
        first = self.store.add(self.src, [u], adapter='bls_api', personas={u['unit_id']: ['macro_rates_en', 'macro_zh']})
        again = self.store.add(self.src, [u], adapter='bls_api')
        self.assertEqual((first['added'], again['added'], again['duplicate']), (1, 0, 1))
        rows = self.store.units(persona='macro_zh')
        self.assertEqual(len(rows), 1)
        rec = rows[0]
        self.assertEqual(rec['licence_tier'], 'A')
        self.assertEqual(rec['attribution']['publisher'], 'Bureau of Labor Statistics')  # registry name wins
        self.assertEqual(rec['source']['adapter'], 'bls_api')
        self.assertEqual(self.store.units(persona='crypto_macro_en'), [])
        reopened = cs.ContentStore(self.store.root)
        self.assertEqual(len(reopened.units()), 1)

    def test_only_writable_tiers_are_stored(self):
        u = dict(unit(self.src), licence_tier='C', usage='topic_only')
        with self.assertRaises(ValueError):
            self.store.add(self.src, [u], adapter='x')

    def test_stats_count_by_tier_adapter_and_persona(self):
        u = unit(self.src)
        self.store.add(self.src, [u], adapter='bls_api', personas={u['unit_id']: ['macro_zh']})
        stats = self.store.stats()
        self.assertEqual(stats['units'], 1)
        self.assertEqual(stats['by_tier'], {'A': 1})
        self.assertEqual(stats['by_adapter'], {'bls_api': 1})
        self.assertEqual(stats['by_persona'], {'macro_zh': 1})


if __name__ == '__main__':
    unittest.main()
