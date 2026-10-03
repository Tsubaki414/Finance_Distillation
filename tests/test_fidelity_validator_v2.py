"""Localized date/scale/heading notation must not hide real fidelity mutations."""
import unittest

from live.numeric_fidelity import inventory, compare, calendar_dates
from live.fidelity import deterministic, numbers
from live.domain_policy import FINANCE
from live.distillation_source import detect_language


class ValidatorNotationTests(unittest.TestCase):
    def findings(self, original, output):
        return FINANCE.deterministic({}, [{'paragraph_id': 'P1', 'exact_text': original}],
            [{'paragraph_id': 'P1', 'text': output}], 'zh', 'localization', detector=lambda _: ('zh', 1))

    def codes(self, original, output):
        return {r['code'] for r in self.findings(original, output)}

    def test_full_abbreviated_month_dates_preserve_exact_calendar_values(self):
        en = 'On Aug. 26, 2026, revenue for the quarter ended July 26, 2026 was $96.2 billion.'
        zh = '2026年8月26日公布截至2026年7月26日的季度营收为962亿美元。'
        self.assertEqual(self.findings(en, zh), [])
        self.assertEqual(calendar_dates(en), calendar_dates(zh))
        self.assertEqual(self.findings(en.replace('26, 2026', '26,2026'), zh), [])

    def test_date_swap_same_numeric_inventory_is_still_held(self):
        en = 'On Aug. 26, 2026, revenue for the quarter ended July 25, 2026 was $96.2 billion.'
        zh = '2026年7月26日公布截至2026年8月25日的季度营收为962亿美元。'
        self.assertIn('calendar_date_binding', self.codes(en, zh))

    def test_wrong_date_day_month_year_are_not_whitelisted(self):
        original = 'On Aug. 26, 2026, revenue was $96.2 billion.'
        for date in ('2026年8月25日', '2026年9月26日', '2025年8月26日'):
            with self.subTest(date=date):
                self.assertIn('calendar_date_binding', self.codes(original, date+'营收为962亿美元。'))

    def test_inserted_metadata_date_stays_held(self):
        self.assertIn('calendar_date_binding', self.codes('Employment increased by 162,000 in August.',
            '2026年9月4日报告，8月就业增加16.2万人。'))

    def test_since_january_and_month_heading_are_not_missing_numbers(self):
        self.assertEqual(numbers('Since January and again in August 2026.'), numbers('自1月以来，随后在2026年8月。'))
        self.assertEqual(numbers('AUGUST 2026'), numbers('2026年8月'))
        self.assertEqual(inventory('It may rise 2 percent.'), inventory('或上涨2%。'))

    def test_absolute_comma_grouped_change_does_not_inherit_endpoint_million(self):
        en = 'The number decreased by 414,000 to 4.4 million in August.'
        zh = '人数在8月减少41.4万人，降至440万人。'
        self.assertEqual(inventory(en), inventory(zh))
        self.assertEqual(self.findings(en, zh), [])
        self.assertIn('new_numeric_value_or_unit', self.codes(en, zh.replace('41.4', '41.5')))

    def test_shared_range_scale_remains_supported_and_wrong_scale_held(self):
        self.assertEqual(inventory('2 to 4 million'), inventory('200万至400万'))
        self.assertTrue(compare('2 to 4 million', '200万至4000万')[0])

    def test_explicit_parenthetical_table_navigation_not_numeric_fact(self):
        en = 'Employment increased by 12,000. (See tables A-1, A-2, and A-3.)'
        zh = '就业增加1.2万人。（见表A-1、A-2和A-3。）'
        self.assertEqual(self.findings(en, zh), [])
        self.assertEqual(self.findings(en, '就业增加1.2万人。'), [])

    def test_table_claims_and_actual_quantities_cannot_be_erased_as_navigation(self):
        self.assertIn('numeric_inventory', self.codes('Table A-1 shows employment fell by 8,000.', '就业减少。'))
        self.assertIn('numeric_inventory', self.codes('Employment fell by 8,000. (See table A-1.)', '就业增加8000人。'.replace('8000', '9000')))

    def test_sign_currency_percentage_points_and_metric_swaps_still_hold(self):
        examples = [
            ('Return was -10%.', '收益为+10%。', 'numeric_inventory'),
            ('Revenue was USD 2 million.', '营收为200万人民币。', 'numeric_inventory'),
            ('Margin fell 1.2 percentage points.', '利润率下降1.2%。', 'numeric_inventory'),
            ('Revenue grew 10%; profit grew 5%.', '营收增长5%；利润增长10%。', 'numeric_metric_binding'),
        ]
        for source, output, expected in examples:
            with self.subTest(source=source): self.assertIn(expected, self.codes(source, output))

    def heading_findings(self, heading, body):
        passages = [{'paragraph_id': 'P1', 'exact_text': 'Household Survey Data'},
                    {'paragraph_id': 'P2', 'exact_text': 'Employment rose in the month.'}]
        segments = [{'paragraph_id': 'P1', 'text': heading}, {'paragraph_id': 'P2', 'text': body}]
        return FINANCE.deterministic({}, passages, segments, 'zh', 'localization', detector=detect_language)

    def test_short_han_heading_only_uses_confirmed_chinese_document_context(self):
        findings = self.heading_findings('家庭调查数据', '本月就业情况发生变化，岗位数量有所增长。')
        self.assertFalse(any(f['code'] == 'wrong_or_uncertain_language' for f in findings))
        for heading, body in [('Household Survey Data', '本月就业情况发生变化，岗位数量有所增长。'),
                              ('家庭调查数据', 'The employment of the economy was in the report.'),
                              ('家庭データ', '本月就业情况发生变化，岗位数量有所增长。')]:
            with self.subTest(heading=heading, body=body):
                findings = self.heading_findings(heading, body)
                self.assertTrue(any(f['paragraph_id']=='P1' and f['code']=='wrong_or_uncertain_language' for f in findings))

    def test_direction_word_and_explicit_sign_need_semantic_review(self):
        # Do not remove a real sign requirement merely to pass this current draft.
        self.assertIn('numeric_inventory', self.codes('Publishing employment (-7,000).', '出版业就业减少7000人。'))


if __name__ == '__main__':
    unittest.main()
