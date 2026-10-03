"""Prompt scaffolding must not reach the finished text.

Every case here was found by reading eighteen pieces blind, after all automated gates had passed
them as ready to ship. None is a wrong number, which is why the numeric audit saw nothing.

Run: .venv/bin/python -B -m unittest tests.test_leak_check
"""
from pathlib import Path
import sys, unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from content.leak_check import check, faults


def codes(text, rows=None):
    return {f['code'] for f in check(text, rows)['findings']}


class MaskMarkers(unittest.TestCase):
    def test_english_marker_blocks(self):
        t = 'Bessent\'s notepad read "Buy Japanese Yen (JPY) $5[figure withheld] bil."'
        self.assertIn('mask_marker_in_output', codes(t))

    def test_chinese_marker_blocks(self):
        self.assertIn('mask_marker_in_output', codes('规模约为〔数字略〕，值得关注。'))

    def test_clean_text_passes(self):
        self.assertEqual(codes('营收 100 万亿韩元，同比增长 51%。'), set())


class PromptRules(unittest.TestCase):
    def test_rule_sentence_blocks(self):
        t = ('The yen rally may be starting. A threshold in the invalidation sentence is the '
             'only figure allowed outside the table.')
        self.assertIn('prompt_rule_in_output', codes(t))

    def test_discussing_thresholds_is_allowed(self):
        t = '若失业率跌破 4.1%，这个判断的失效条件就触发了。'
        self.assertNotIn('prompt_rule_in_output', codes(t))


class SkeletonHeadings(unittest.TestCase):
    def test_heading_used_as_prose_blocks(self):
        t = '价格与工时这条线显示平均时薪环比上涨 0.3%，企业成本压力仍在。'
        self.assertIn('skeleton_heading_in_prose', codes(t))

    def test_ordinary_wording_passes(self):
        t = '工资与工时的组合说明企业成本压力仍在。'
        self.assertNotIn('skeleton_heading_in_prose', codes(t))


class SlotLabels(unittest.TestCase):
    def test_slot_label_blocks(self):
        self.assertIn('slot_label_in_output', codes('L01 Yen intervention 98 billion dollars.'))


class Endings(unittest.TestCase):
    def test_truncated_on_a_figure_blocks(self):
        rows = [{'text': '失效条件：若私人非农平均周工时变化 0.'}]
        self.assertIn('truncated_ending', codes('失效条件：若私人非农平均周工时变化 0.', rows))

    def test_missing_terminator_blocks(self):
        rows = [{'text': '这说明劳动力供给正在收缩'}]
        self.assertIn('unterminated_ending', codes('这说明劳动力供给正在收缩', rows))

    def test_normal_ending_passes(self):
        rows = [{'text': '若失业率跌破 4.1%，判断失效。'}]
        self.assertEqual(codes('若失业率跌破 4.1%，判断失效。', rows), set())

    def test_a_figure_mid_sentence_is_fine(self):
        rows = [{'text': '营收增长 51%，这支撑了当前判断。'}]
        self.assertEqual(codes('营收增长 51%，这支撑了当前判断。', rows), set())


class Feedback(unittest.TestCase):
    def test_faults_are_actionable_in_both_languages(self):
        r = check('规模约为〔数字略〕。')
        self.assertTrue(faults(r, 'zh'))
        self.assertTrue(faults(r, 'en'))
