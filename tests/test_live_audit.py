"""The live numeric audit: same strictness on the number, no opinion about notation.

String matching rejected a correctly written draft three ways — "75.0%" against a slot rendered
"75 percent", "$2.46" against "2.46 dollars", and a whole range against its own slot because the
scanner split it into two figures. Each of those is the writer being right and the audit being
wrong. Value-and-unit comparison keeps every wrong figure invalid.

Run: .venv/bin/python -B -m unittest tests.test_live_audit
"""
from pathlib import Path
import sys, unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))
import write as W

SLOTS = [
    {'slot_id': 'a', 'value_rendered': '75 percent'},
    {'slot_id': 'b', 'value_rendered': '2.46 dollars'},
    {'slot_id': 'c', 'value_rendered': '16 percent to 18 percent'},
    {'slot_id': 'd', 'value_rendered': '2 万亿日元'},
    {'slot_id': 'e', 'value_rendered': '0.5 个百分点'},
    {'slot_id': 'f', 'value_rendered': '1.1% 至 2.5%'},
]


def audit(text):
    return W.audit(text, SLOTS)


class NotationIsNotRestatement(unittest.TestCase):
    def test_percent_sign_matches_the_word(self):
        used, bad, _ = audit('margins were 75.0% for the quarter')
        self.assertEqual(bad, [])
        self.assertIn('a', used)

    def test_currency_symbol_matches_the_word(self):
        used, bad, _ = audit('earnings per share were $2.46 under GAAP')
        self.assertEqual(bad, [])
        self.assertIn('b', used)

    def test_chinese_scale_word(self):
        used, bad, _ = audit('规模为 2 万亿日元')
        self.assertEqual(bad, [])
        self.assertIn('d', used)


class RangesAreOneFigure(unittest.TestCase):
    def test_whole_range_matches(self):
        used, bad, _ = audit('the tax rate 16 percent to 18 percent reflects the mix')
        self.assertEqual(bad, [])
        self.assertIn('c', used)

    def test_chinese_range_matches(self):
        used, bad, _ = audit('自然利率区间被估算为 1.1% 至 2.5%。')
        self.assertEqual(bad, [])
        self.assertIn('f', used)

    def test_a_lone_bound_is_still_rejected(self):
        """Half a range is how "expected to be between 16 percent" reached a draft."""
        _, bad, _ = audit('the tax rate is expected to be 16 percent')
        self.assertTrue(bad)

    def test_range_bounds_are_not_double_counted(self):
        used, bad, _ = audit('16 percent to 18 percent')
        self.assertEqual(used, ['c'])


class WrongFiguresStillFail(unittest.TestCase):
    def test_a_different_number_is_rejected(self):
        _, bad, _ = audit('margins were 71 percent')
        self.assertIn('71 percent', bad)

    def test_right_number_wrong_unit_is_rejected(self):
        _, bad, _ = audit('the gap was 75 个百分点')
        self.assertTrue(bad)

    def test_scale_error_is_rejected(self):
        _, bad, _ = audit('规模为 2 亿日元')
        self.assertTrue(bad)

    def test_threshold_in_a_condition_is_reported_separately(self):
        used, bad, prop = audit('若利率跌破 3.5%，判断失效。')
        self.assertEqual(bad, [])
        self.assertIn('3.5%', prop)


class SlotIdsNeverAppear(unittest.TestCase):
    def test_a_leaked_label_is_caught(self):
        rows = [{'text': 'L01 Yen intervention 98 billion dollars', 'slot_ids': ['a'],
                 'model_written_numbers': [], 'proposed_thresholds': [], 'kind': 'fact'}]
        self.assertTrue(W.SLOT_ID_LEAK.search(rows[0]['text']))

    def test_ordinary_text_is_not_flagged(self):
        self.assertIsNone(W.SLOT_ID_LEAK.search('margins were 75 percent in Q2'))
