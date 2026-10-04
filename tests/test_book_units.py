import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.book_units as bu
from scripts.book_extract_text import strip_ads


class BookUnitsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for d in ('text', 'clean', 'llm'):
            (self.root / d).mkdir()
        self.meta = {'b': dict(title='书', title_en='Book', author='A. Author', focus='x',
                               routes=['trading_shortterm'])}
        (self.root / 'clean' / 'b.txt').write_text('第一段：止损是交易者的生命线，不设止损迟早会爆仓。\n\n第二段：单笔风险不超过总资金的2%。\n')

    def tearDown(self):
        self.tmp.cleanup()

    def llm(self, units):
        (self.root / 'llm' / 'b.000.json').write_text(json.dumps({'engine': 'test', 'value': {'units': units}}, ensure_ascii=False))

    def unit(self, **kw):
        base = {'kind': 'aphorism', 'statement': 'A. Author treats the stop-loss as non-negotiable.',
                'statement_zh': '作者认为止损不可商量。', 'evidence': ['止损是交易者的生命线'], 'short_quote': '止损是交易者的生命线'}
        base.update(kw)
        return base

    def build(self):
        with patch.object(bu, 'ROOT', self.root):
            return bu.build(self.meta)

    def test_ads_stripped(self):
        self.assertEqual(strip_ads('【艾略特波浪理论】加VZBB3465赠送课程.pdf'), '【艾略特波浪理论】.pdf')

    def test_valid_unit_is_evergreen_paraphrase_book_unit(self):
        self.llm([self.unit()])
        staged, rejected = self.build()
        self.assertEqual(rejected, [])
        u = staged[0]['unit']
        self.assertEqual((u['freshness_class'], u['licence_tier'], u['usage'], u['source_type']),
                         ('evergreen', 'B', 'paraphrase', 'book'))
        self.assertEqual(u['licence_note'], bu.LICENCE_NOTE)
        span = u['source_spans'][0]
        text = (self.root / 'clean' / 'b.txt').read_text()
        self.assertEqual(text[span['start']:span['end']], span['exact_text'])
        self.assertLessEqual(u['short_quote']['chars'], 30)

    def test_facts_hallucinated_evidence_and_dates_rejected(self):
        self.llm([self.unit(kind='fact'), self.unit(evidence=['这句话不在书里出现过']),
                  self.unit(statement='In 1987 the author lost money.'),
                  self.unit(statement='Risk at most 5% per trade.', evidence=['单笔风险不超过总资金的2%'])])
        staged, rejected = self.build()
        self.assertEqual(staged, [])
        self.assertEqual(len(rejected), 4)

    def test_rule_number_allowed_when_cited(self):
        self.llm([self.unit(kind='view', statement='The author caps risk on any trade at 2% of capital.',
                            evidence=['单笔风险不超过总资金的2%'], short_quote=None,
                            view={'subject': 'position risk', 'direction': 'neutral', 'conviction': 'high',
                                  'horizon': 'unspecified', 'reasoning': ['Cap single-trade risk.']})])
        staged, rejected = self.build()
        self.assertEqual(rejected, [])
        self.assertIn('view', staged[0]['unit'])

    def test_long_quote_dropped(self):
        long_quote = '第一段：止损是交易者的生命线，不设止损迟早会爆仓。'
        self.llm([self.unit(short_quote=long_quote * 2)])
        staged, _ = self.build()
        self.assertNotIn('short_quote', staged[0]['unit'])

    def test_dedupe_against_store_and_within_books(self):
        self.llm([self.unit(), self.unit(evidence=['不设止损迟早会爆仓'])])
        staged, _ = self.build()
        keep, dups = bu.dedupe(staged, [])
        self.assertEqual(len(keep), 1)
        keep, dups = bu.dedupe(staged, [{'unit_id': 'cu-x', 'unit': {'statement': staged[0]['unit']['statement']}}])
        self.assertEqual(keep, [])


if __name__ == '__main__':
    unittest.main()
