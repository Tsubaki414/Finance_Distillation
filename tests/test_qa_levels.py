"""Post QA: numbers warn; legal and unsupported unknown checks fail closed."""
import unittest

from live import compose, qa_levels
from tests.test_compose import Fake, GOOD_BODY, run


def levels(result):
    return {f['code']: f['level'] for f in result['post_checks']}


class PublishYearTests(unittest.TestCase):
    """Approved 2026-10-04: the year of the source's published_at may appear in a post."""
    UNITS = [{'numbers': [], 'published_at': '2026-10-02T00:00:00Z',
              'source_spans': [{'exact_text': 'Memory prices kept rising in the quarter.'}]}]

    def codes(self, body):
        return {f['code'] for f in compose.number_findings(body, self.UNITS)}

    def test_publish_year_is_allowed(self):
        self.assertNotIn('number_not_in_units', self.codes('2026年存储价格继续上涨。'))

    def test_other_years_still_block(self):
        self.assertIn('number_not_in_units', self.codes('2025年存储价格继续上涨。'))
        self.assertIn('number_not_in_units', self.codes('2027年存储价格继续上涨。'))

    def test_no_publish_date_no_allowance(self):
        units = [{**self.UNITS[0], 'published_at': None}]
        self.assertIn('number_not_in_units', {f['code'] for f in compose.number_findings('2026年', units)})


class LevelTableTests(unittest.TestCase):
    def test_hard_codes(self):
        for code in ('licence_tier_not_allowed', 'd_tier_source_leak', 'quote_not_exact',
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
        self.assertEqual({f['code'] for f in result['post_checks']}, {'verify_source'})
        self.assertTrue(all(f['level'] == 'soft' for f in result['post_checks']))
        self.assertEqual(result['qa'], {'hard': [], 'soft': ['verify_source']})
        self.assertEqual(result['draft_status'], 'draft_ready')

    def test_short_post_is_a_warning(self):
        result, _ = run(Fake(body='美光营收增长4.8倍，达到542.3亿美元。'), post_type='data_take')
        self.assertEqual(levels(result)['length_out_of_range'], 'soft')
        self.assertEqual(result['draft_status'], 'draft_ready')
        self.assertIn('length_out_of_range', result['qa']['soft'])

    def test_template_phrase_is_a_warning(self):
        result, _ = run(Fake(body='不得不说，' + GOOD_BODY), post_type='data_take')
        self.assertEqual(levels(result)['template_phrase'], 'soft')
        self.assertEqual(result['draft_status'], 'draft_ready')

    def test_editorial_cliche_is_hard(self):
        # fix26 (Fiona Oct 7): 值得注意的是 moved from SOFT template_phrase to the HARD Sirius editorial-style block
        result, _ = run(Fake(body='值得注意的是，' + GOOD_BODY), post_type='data_take')
        self.assertEqual(levels(result)['editorial_cliche'], 'hard')
        self.assertEqual(result['draft_status'], 'needs_review')

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

    def test_number_mismatch_warns(self):
        result, _ = run(Fake(body=GOOD_BODY.replace('69.5%', '72%')), post_type='data_take')
        self.assertEqual(levels(result)['number_not_in_units'], 'soft')
        # Oct 7 Sirius item 2: the ungrounded number itself is HARD -> needs_review after the one rewrite
        self.assertEqual(levels(result)['ungrounded_number'], 'hard')
        self.assertEqual(result['draft_status'], 'needs_review')

    def test_period_mismatch_warns(self):
        result, _ = run(Fake(body=GOOD_BODY.replace('这个季度', '第三季度')), post_type='data_take')
        self.assertEqual(levels(result)['period_not_in_units'], 'soft')
        self.assertEqual(result['draft_status'], 'draft_ready')

    def test_metric_binding_warns(self):
        body = GOOD_BODY.replace('营业利润率为69.5%', '营收占比69.5%').replace('营收同比增长4.8倍', '利润率同比增长4.8倍')
        result, _ = run(Fake(body=body), post_type='data_take')
        self.assertEqual(levels(result)['number_metric_binding'], 'soft')
        self.assertEqual(result['draft_status'], 'draft_ready')

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

    def test_unsourced_number_words_and_sourced_ones_warn(self):
        result, _ = run(Fake(body=GOOD_BODY + '利润几乎翻倍。'), post_type='data_take')
        self.assertEqual(levels(result)['number_words'], 'soft')
        self.assertEqual(result['draft_status'], 'draft_ready')
        self.assertEqual(qa_levels.level({'code': 'number_words', 'sourced': True}, frame_found=True), 'soft')

    def test_number_word_must_match_its_own_sourced_multiple(self):
        units = [{'numbers': [], 'source_spans': [{'exact_text': 'Revenue doubled in the quarter.'}]}]
        same = {f['detail']: f['sourced'] for f in compose.number_findings('营收翻倍。', units) if f['code'] == 'number_words'}
        other = {f['detail']: f['sourced'] for f in compose.number_findings('营收增长三倍。', units) if f['code'] == 'number_words'}
        self.assertEqual(same, {'翻倍': True})
        self.assertEqual(other, {'三倍': False})

    def test_publishable_never_changes(self):
        result, _ = run(Fake(body='值得注意的是，' + GOOD_BODY), post_type='data_take')
        self.assertFalse(result['publishable'])
        self.assertEqual(result['status'], 'held')


if __name__ == '__main__':
    unittest.main()
