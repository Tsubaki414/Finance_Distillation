"""Two-level post QA (fd-phase0, after P0-4e).

HARD findings block a draft (draft_status needs_review): numbers / periods /
metric bindings that do not match the source units, D-tier source leakage or a
licence tier the post type does not accept, a same-language direct quote that
is not an exact substring of a source span, a required attribution frame that
is missing, and unknown codes (fail closed). Everything else is a SOFT warning:
the draft stays draft_ready and carries the warning (template phrases, length
out of range, the source named in the body when the frame is present,
attribution phrasing outside the frame, first person / borrowed experience,
code fences, translated quotes).
"""
import unittest

from live import compose, qa_levels
from tests.test_compose import Fake, GOOD_BODY, run


def levels(result):
    return {f['code']: f['level'] for f in result['post_checks']}


class LevelTableTests(unittest.TestCase):
    def test_hard_codes(self):
        for code in ('number_not_in_units', 'period_not_in_units', 'number_metric_binding',
                     'licence_tier_not_allowed', 'd_tier_source_leak', 'quote_not_exact',
                     'missing_attribution_frame'):
            self.assertEqual(qa_levels.level({'code': code}, frame_found=True), 'hard', code)

    def test_soft_codes(self):
        for code in ('template_phrase', 'length_out_of_range', 'attribution_outside_frame',
                     'author_identity', 'code_fence', 'translated_quote'):
            self.assertEqual(qa_levels.level({'code': code}, frame_found=True), 'soft', code)

    def test_source_name_in_body_is_soft_only_when_the_frame_is_there(self):
        self.assertEqual(qa_levels.level({'code': 'provenance_in_body'}, frame_found=True), 'soft')
        self.assertEqual(qa_levels.level({'code': 'provenance_in_body'}, frame_found=False), 'hard')

    def test_unknown_code_fails_closed(self):
        self.assertEqual(qa_levels.level({'code': 'something_new'}, frame_found=True), 'hard')

    def test_status_only_hard_blocks(self):
        soft = [{'code': 'template_phrase', 'level': 'soft'}]
        hard = soft + [{'code': 'number_not_in_units', 'level': 'hard'}]
        self.assertEqual(qa_levels.draft_status(soft), 'draft_ready')
        self.assertEqual(qa_levels.draft_status(hard), 'needs_review')
        self.assertEqual(qa_levels.draft_status([]), 'draft_ready')


class ComposeLevelTests(unittest.TestCase):
    def test_good_post_has_no_findings(self):
        result, _ = run(post_type='data_take')
        self.assertEqual(result['post_checks'], [])
        self.assertEqual(result['qa'], {'hard': [], 'soft': []})
        self.assertEqual(result['draft_status'], 'draft_ready')

    def test_short_post_is_a_warning(self):
        result, _ = run(Fake(body='美光营收增长4.8倍，达到542.3亿美元。'), post_type='data_take')
        self.assertEqual(levels(result)['length_out_of_range'], 'soft')
        self.assertEqual(result['draft_status'], 'draft_ready')
        self.assertIn('length_out_of_range', result['qa']['soft'])

    def test_template_phrase_is_a_warning(self):
        result, _ = run(Fake(body='值得注意的是，' + GOOD_BODY), post_type='data_take')
        self.assertEqual(levels(result)['template_phrase'], 'soft')
        self.assertEqual(result['draft_status'], 'draft_ready')

    def test_source_name_in_body_with_frame_is_a_warning(self):
        result, _ = run(Fake(body=GOOD_BODY + 'The Next Platform 的判断也是如此。'), post_type='data_take')
        self.assertEqual(levels(result)['provenance_in_body'], 'soft')
        self.assertEqual(result['draft_status'], 'draft_ready')

    def test_first_person_is_a_warning_with_a_fix_hint(self):
        result, _ = run(Fake(body='我一直在跟踪美光。' + GOOD_BODY), post_type='data_take')
        finding = next(f for f in result['post_checks'] if f['code'] == 'author_identity')
        self.assertEqual(finding['level'], 'soft')
        self.assertIn('fix', finding)
        self.assertEqual(result['draft_status'], 'draft_ready')

    def test_number_mismatch_blocks(self):
        result, _ = run(Fake(body=GOOD_BODY.replace('69.5%', '72%')), post_type='data_take')
        self.assertEqual(levels(result)['number_not_in_units'], 'hard')
        self.assertEqual(result['draft_status'], 'needs_review')

    def test_period_mismatch_blocks(self):
        result, _ = run(Fake(body=GOOD_BODY.replace('这个季度', '第三季度')), post_type='data_take')
        self.assertEqual(levels(result)['period_not_in_units'], 'hard')
        self.assertEqual(result['draft_status'], 'needs_review')

    def test_metric_binding_blocks(self):
        body = GOOD_BODY.replace('营业利润率为69.5%', '营收占比69.5%').replace('营收同比增长4.8倍', '利润率同比增长4.8倍')
        result, _ = run(Fake(body=body), post_type='data_take')
        self.assertEqual(levels(result)['number_metric_binding'], 'hard')
        self.assertEqual(result['draft_status'], 'needs_review')

    def test_d_tier_source_leak_blocks(self):
        result, _ = run(Fake(body=GOOD_BODY + '慧博上的卖方研报也给出了类似判断。'), post_type='data_take')
        self.assertEqual(levels(result)['d_tier_source_leak'], 'hard')
        self.assertEqual(result['draft_status'], 'needs_review')

    def test_same_language_quote_must_be_exact(self):
        bad = GOOD_BODY + ' "building a fab takes decades"'
        result, _ = run(Fake(body=bad), post_type='data_take')
        self.assertEqual(levels(result)['quote_not_exact'], 'hard')
        self.assertEqual(result['draft_status'], 'needs_review')
        good = GOOD_BODY + ' "building a fab takes years"'
        result, _ = run(Fake(body=good), post_type='data_take')
        self.assertNotIn('quote_not_exact', levels(result))
        self.assertEqual(result['draft_status'], 'draft_ready')

    def test_translated_quote_is_a_warning(self):
        result, _ = run(Fake(body=GOOD_BODY + '原文的说法是“建一座晶圆厂要好几年”。'), post_type='data_take')
        self.assertEqual(levels(result).get('translated_quote'), 'soft')
        self.assertEqual(result['draft_status'], 'draft_ready')

    def test_unsourced_number_words_block_but_sourced_ones_warn(self):
        result, _ = run(Fake(body=GOOD_BODY + '利润几乎翻倍。'), post_type='data_take')
        self.assertEqual(levels(result)['number_words'], 'hard')
        self.assertEqual(result['draft_status'], 'needs_review')
        self.assertEqual(qa_levels.level({'code': 'number_words', 'sourced': True}, frame_found=True), 'soft')

    def test_publishable_never_changes(self):
        result, _ = run(Fake(body='值得注意的是，' + GOOD_BODY), post_type='data_take')
        self.assertFalse(result['publishable'])
        self.assertEqual(result['status'], 'held')


if __name__ == '__main__':
    unittest.main()
