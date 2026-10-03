"""Machine tells, and the rule that a tell must be validated before it can block.

The English rule set is adapted from skyf0xx/hedgehog-core-copywriting-prose-engineering. Most of
it did not survive measurement against this project's corpus, and the tests below pin both the
rules that were kept and the reason the others are off — so a future edit cannot quietly re-enable
a rule that rejects the writers being imitated.

Run: .venv/bin/python -B -m unittest tests.test_tells
"""
from pathlib import Path
import sys, unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from content import tells


def codes(text, lang=None):
    return {f['code'] for f in tells.check(text, lang)['findings']}


def blocking(text, lang=None):
    return {f['code'] for f in tells.check(text, lang)['findings']
            if f['severity'] == tells.BLOCKING}


class FigureDensity(unittest.TestCase):
    """The clearest structural tell: machine 0.82-0.86, human 0.33-0.42."""

    def test_a_figure_in_every_sentence_blocks(self):
        t = ('营收 100 亿元。利润 20 亿元。现金 88 亿元。增速 51%。'
             '毛利率 76%。资本开支 30 亿元。')
        self.assertIn('every_sentence_carries_a_figure', codes(t, 'zh'))

    def test_argument_between_figures_passes(self):
        t = ('营收 100 亿元，比去年明显回升。这说明需求端仍有支撑，'
             '但成本的压力并没有同步缓解。利润率 76%，高得不太正常。'
             '我倾向于认为这里面有一次性因素。若下季度回落，判断就要改。')
        self.assertNotIn('every_sentence_carries_a_figure', codes(t, 'zh'))

    def test_short_pieces_are_not_judged(self):
        """Four sentences is too few for a share to mean anything."""
        self.assertNotIn('every_sentence_carries_a_figure',
                         codes('营收 100 亿元。利润 20 亿元。现金 88 亿元。', 'zh'))

    def test_english_ceiling_is_lower(self):
        self.assertLess(tells.FIGURE_DENSITY_CEILING['en'],
                        tells.FIGURE_DENSITY_CEILING['zh'])

    def test_density_is_reported_even_when_passing(self):
        r = tells.check('营收回升。成本没有同步下降。我维持原判断。若下季回落再改。这是关键。', 'zh')
        self.assertIsNotNone(r['figure_density'])


class ValidatedRulesOnly(unittest.TestCase):
    def test_copula_avoidance_blocks_in_chinese(self):
        t = '该数据构成了需求端的支撑，体现了结构性变化，反映出成本压力正在积累。'
        self.assertIn('overused_copula_avoidance', codes(t, 'zh'))

    def test_english_machine_vocabulary_blocks(self):
        self.assertIn('machine_vocabulary',
                      codes('This robust framework will leverage seamless synergy.', 'en'))

    def test_chinese_vocabulary_is_reported_not_blocked(self):
        """Those words appear in 1.7% of real posts and 0% of generated ones, so they measure
        the donors rather than the machine."""
        r = tells.check('这一变化彰显了产业升级的重要意义。', 'zh')
        self.assertIn('machine_vocabulary_observed', {f['code'] for f in r['findings']})
        self.assertEqual([f['severity'] for f in r['findings']
                          if f['code'] == 'machine_vocabulary_observed'], ['warning'])

    def test_rule_of_three_is_disabled_and_says_why(self):
        self.assertIn('rule_of_three', tells.DISABLED_RULES)
        self.assertNotIn('rule_of_three', tells.STRUCTURAL_LIMIT)

    def test_disabled_rules_are_still_measured(self):
        s = tells.scan('营收、利润、现金流都在改善。', 'zh')
        self.assertIn('rule_of_three', s['structural_counts'])


class CleanTextPasses(unittest.TestCase):
    def test_ordinary_chinese_analysis(self):
        t = ('营收同比增长 51%，这个速度比市场想的要快。但成本端并没有跟上，'
             '利润率的改善更多来自一次性因素。我暂时不加仓。'
             '要看到下季度的毛利率仍在这个水平，才算确认。否则这轮就是估值修复而已。')
        self.assertEqual(codes(t, 'zh'), set())

    def test_ordinary_english_analysis(self):
        """Nothing blocking. A sentence-length *warning* is expected and is not a defect.

        This sample's CV is 0.451, between the p10 floor (0.364) and the p25 warning line (0.558)
        for a five-sentence English piece. The warning tier fires on a quarter of the donors' own
        posts by construction, so asserting no findings at all would be asserting that a quarter
        of real writing is flawless by this measure — which is not what a percentile means.
        """
        t = ('Payrolls rose 162,000 last month. That is faster than the run rate, '
             'though the mix looks weaker than the headline. I am not changing my view yet. '
             'What would change it is a second month of the same. Until then this is noise.')
        self.assertEqual(blocking(t, 'en'), set())
        self.assertIn('sentence_length_near_the_edge', codes(t, 'en'))
