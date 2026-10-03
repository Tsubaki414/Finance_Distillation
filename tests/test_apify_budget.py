"""Compute overhead is independent of estimated model cost; no real spending."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ml import budget


class ApifyBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in {
            'STORE': self.root,
            'LEDGER': self.root / 'spend.json',
            'RUNS': self.root / 'reviews.jsonl',
            'DISTILLATION_RUNS': self.root / 'distillation.jsonl',
        }.items():
            handle = patch.object(budget, name, value)
            handle.start()
            self.addCleanup(handle.stop)
        self.messages = [{'role': 'user', 'content': 'Exact source 原文'}]
        self.model = 'apify/anthropic/claude-opus-5'
        budget.LEDGER.write_text(json.dumps({'cap_usd': 5.0, 'spent_usd': 0.0, 'calls': 0}))
        self.model_estimate = budget.cost_of(
            self.model, len(json.dumps(self.messages, ensure_ascii=False).encode('utf-8')) + 256, 100)

    def reserve(self, call_id='call', overhead=0.25):
        return budget.reserve(self.model, self.messages, 100, call_id, overhead_usd=overhead)

    def row(self, call_id='call'):
        return budget._load()['reservations'][call_id]

    def test_known_model_and_compute_usage_reconciled_separately(self):
        total = self.reserve()
        self.assertAlmostEqual(total, self.model_estimate + 0.25)
        self.assertEqual(self.row()['model_estimate'], self.model_estimate)
        self.assertEqual(self.row()['overhead_estimate'], 0.25)
        actual = budget.settle('call', {'prompt_tokens': 20, 'completion_tokens': 8},
                               overhead_actual_usd=0.017)
        self.assertAlmostEqual(actual, budget.cost_of(self.model, 20, 8) + 0.017)
        self.assertEqual(self.row()['overhead_actual_usd'], 0.017)
        self.assertAlmostEqual(budget.spent(), round(actual, 6))
        self.assertEqual(budget.cap(), 5.0)

    def test_unknown_compute_keeps_reserved_overhead(self):
        self.reserve()
        total = budget.settle('call', {'prompt_tokens': 20, 'completion_tokens': 8})
        self.assertAlmostEqual(total, budget.cost_of(self.model, 20, 8) + 0.25)
        self.assertEqual(self.row()['overhead_cost'], 0.25)
        self.assertIsNone(self.row()['overhead_actual_usd'])

    def test_unknown_model_usage_does_not_double_count_reserved_overhead(self):
        self.reserve()
        total = budget.settle('call', None, overhead_actual_usd=0.04)
        self.assertAlmostEqual(total, self.model_estimate + 0.04)
        self.assertEqual(self.row()['model_cost'], self.model_estimate)

    def test_all_unknown_keeps_original_total_and_zero_compute_is_known(self):
        estimate = self.reserve()
        self.assertEqual(budget.settle('call', {}), estimate)
        self.reserve('zero')
        self.assertEqual(budget.settle('zero', None, overhead_actual_usd=0), self.model_estimate)
        self.assertEqual(self.row('zero')['overhead_cost'], 0)

    def test_cap_includes_compute_and_rejection_does_not_write(self):
        before = {'cap_usd': self.model_estimate + 0.20, 'spent_usd': 0, 'calls': 0}
        budget.LEDGER.write_text(json.dumps(before))
        old = budget.LEDGER.read_bytes()
        with self.assertRaises(budget.BudgetExceeded):
            self.reserve()
        self.assertEqual(budget.LEDGER.read_bytes(), old)
        self.assertFalse(budget.DISTILLATION_RUNS.exists())

    def test_invalid_reservation_amounts_refused_before_writing(self):
        old = budget.LEDGER.read_bytes()
        for value in [-1, float('nan'), float('inf'), -float('inf'), True, '0.25']:
            with self.subTest(overhead=value), self.assertRaises(ValueError):
                self.reserve(overhead=value)
            with self.subTest(max_tokens=value), self.assertRaises(ValueError):
                budget.reserve(self.model, self.messages, value, 'invalid')
        self.assertEqual(budget.LEDGER.read_bytes(), old)

    def test_invalid_settlement_amounts_leave_reservation_untouched(self):
        self.reserve()
        old = budget.LEDGER.read_bytes()
        for value in [-1, float('nan'), float('inf'), True, '0.1']:
            with self.subTest(overhead=value), self.assertRaises(ValueError):
                budget.settle('call', None, overhead_actual_usd=value)
            with self.subTest(tokens=value), self.assertRaises(ValueError):
                budget.settle('call', {'prompt_tokens': value, 'completion_tokens': 0})
        self.assertEqual(budget.LEDGER.read_bytes(), old)
        self.assertFalse(budget.DISTILLATION_RUNS.exists())

    def test_legacy_call_retains_exact_schema_and_cost(self):
        total = budget.reserve(self.model, self.messages, 100, 'legacy')
        self.assertEqual(total, self.model_estimate)
        self.assertEqual(self.row('legacy'), {'model': self.model, 'estimate': total, 'settled': False})
        usage = {'prompt_tokens': 20, 'completion_tokens': 8}
        cost = budget.settle('legacy', usage)
        self.assertEqual(cost, budget.cost_of(self.model, 20, 8))
        self.assertEqual(self.row('legacy'), {'model': self.model, 'estimate': total,
                                            'settled': True, 'cost': cost, 'usage': usage})
        self.assertEqual(budget._load()['last']['basis'], 'token/rate estimate; not invoice')
        self.assertEqual(set(budget._load()['last']), {'at', 'model', 'usd', 'basis'})
        self.assertEqual(budget._load()['calls'], 1)
        self.assertEqual(budget.cap(), 5.0)

    def test_legacy_unknown_usage_keeps_original_reserve(self):
        estimate = budget.reserve(self.model, self.messages, 100, 'legacy')
        self.assertEqual(budget.settle('legacy', None), estimate)
        self.assertNotIn('overhead_estimate', self.row('legacy'))

    def test_settlement_is_idempotent_no_second_cost_or_journal_entry(self):
        self.reserve()
        first = budget.settle('call', None, overhead_actual_usd=0.04)
        old = budget.LEDGER.read_bytes()
        self.assertEqual(budget.settle('call', {'prompt_tokens': 2, 'completion_tokens': 1},
                                       overhead_actual_usd=0.01), first)
        self.assertEqual(budget.LEDGER.read_bytes(), old)
        self.assertEqual(len(budget.DISTILLATION_RUNS.read_text().strip().split('\n')), 1)

    def test_recost_keeps_reported_compute_and_unknown_usage_reserve(self):
        self.reserve('known')
        self.reserve('unknown')
        budget.settle('known', {'prompt_tokens': 20, 'completion_tokens': 8}, overhead_actual_usd=0.04)
        budget.settle('unknown', None)
        budget.RUNS.write_text('')
        with patch.object(budget, 'price_of', return_value=(30.0, 150.0)):
            result = budget.recost()
            expected = budget.cost_of(self.model, 20, 8) + 0.04 + self.model_estimate + 0.25
        self.assertAlmostEqual(result['spent_usd'], round(expected, 6))
        self.assertEqual(result['cap_usd'], 5.0)
        self.assertEqual(result['calls'], 2)

    def test_recost_keeps_pending_compute_reserve(self):
        estimate = self.reserve()
        budget.RUNS.write_text('')
        self.assertEqual(budget.recost()['spent_usd'], round(estimate, 6))
        self.assertFalse(self.row()['settled'])


if __name__ == '__main__':
    unittest.main()
