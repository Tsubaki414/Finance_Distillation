"""EXTRACT keeps the units that pass the contract and drops the ones that do not.

One bad number or span used to fail the whole source (3 of 9 relay samples on
2026-10-04). A dropped unit never reaches COMPOSE, so nothing unverified gets
into a post; the drop is recorded with its reason. A response whose units all
fail is still a ContractError (the output is unusable).
"""
import unittest

from live import compose, content_units as cu
from live.distillation import ContractError
from tests.test_extract_contract import Fake, SOURCE, unit


class PartialExtractTests(unittest.TestCase):
    def test_bad_unit_is_dropped_and_recorded(self):
        bad = unit(numbers=[{'text': '69.5%', 'metric': 'operating margin', 'period': 'q', 'span_ref': 0}])
        result = cu.extract(SOURCE, Fake([unit(), bad]), licence_tier='B')
        self.assertEqual(len(result['units']), 1)
        self.assertEqual(len(result['dropped_units']), 1)
        self.assertEqual(result['dropped_units'][0]['index'], 1)
        self.assertIn('number text is not in its span', result['dropped_units'][0]['reason'])

    def test_forged_span_unit_dropped_others_kept(self):
        forged = unit(source_spans=[{'paragraph_id': 'P1', 'exact_text': 'Micron revenue soared'}])
        result = cu.extract(SOURCE, Fake([forged, unit()]), licence_tier='B')
        self.assertEqual([d['index'] for d in result['dropped_units']], [0])
        self.assertEqual(len(result['units']), 1)

    def test_all_units_bad_is_still_a_contract_error(self):
        bad = unit(numbers=[{'text': 'revenue', 'metric': 'revenue', 'period': 'q', 'span_ref': 0}])
        with self.assertRaises(ContractError):
            cu.extract(SOURCE, Fake([bad, bad]), licence_tier='B')

    def test_token_budgets_leave_room(self):
        self.assertGreaterEqual(cu.MAX_TOKENS, 12000)
        self.assertGreaterEqual(compose.MAX_TOKENS, 6000)


if __name__ == '__main__':
    unittest.main()
