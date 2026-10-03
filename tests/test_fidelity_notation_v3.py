"""Notation repairs must retain real unit/date/ownership failures. No model calls."""
import copy
import unittest

from live.domain_policy import FINANCE
from live.numeric_fidelity import compare, inventory, verified_time_anchors
from live.source_hygiene import annotate, postcheck
from live.distillation_source import source_record


class NumericNotationRepairs(unittest.TestCase):
    source = {'published_at':'2026-09-29T14:24:25+00:00'}

    def checks(self,original,output,source=None):
        return FINANCE.deterministic(source or {},[{'paragraph_id':'P1','exact_text':original}],
            [{'paragraph_id':'P1','text':output}],'zh','localization',detector=lambda _:('zh',1))

    def test_hyphenated_basis_points_preserve_unit_and_value(self):
        original='A 22-basis-point decline follows a 2.5 percent increase.'
        self.assertEqual(self.checks(original,'增加2.5%后下降22个基点。'),[])
        self.assertTrue(self.checks(original,'增加2.5%后下降23个基点。'))
        self.assertTrue(self.checks(original,'增加2.5%后下降22%。'))
        self.assertEqual(inventory('22\u2011basis\u2011point'),inventory('22基点'))

    def test_multiple_to_amount_does_not_inherit_billions_or_currency(self):
        original='DRAM rose 4.4X to $39.77 billion. Flash sales rose 6.2X to $14.1 billion.'
        output='DRAM增长4.4倍至397.7亿美元。闪存销售额增长6.2倍至141亿美元。'
        self.assertEqual(compare(original,output),([],[]))
        self.assertEqual(self.checks(original,output),[])
        for changed in (output.replace('4.4倍','4.5倍'),output.replace('6.2倍','6.2%'),
                        output.replace('397.7亿美元','397.7亿元'),output.replace('141亿美元','1410亿美元')):
            with self.subTest(changed=changed):self.assertTrue(self.checks(original,changed))

    def test_same_unit_shared_ranges_keep_scale(self):
        self.assertEqual(inventory('$2 to $4 billion'),inventory('20亿至40亿美元'))
        self.assertEqual(inventory('4.4X to 6.2X'),inventory('4.4至6.2倍'))
        self.assertTrue(compare('$2 to $4 billion','20亿至400亿美元')[0])

    def test_unicode_negative_sign_is_not_silently_lost(self):
        self.assertEqual(inventory('−3.6 percent'),inventory('-3.6%'))
        self.assertTrue(compare('−3.6 percent','+3.6%')[0])
        self.assertTrue(self.checks('−3.6 percent','上涨3.6%'))

    def test_only_source_supported_adjacent_year_and_month_anchors_are_exempt(self):
        examples=[('Now the shares are worth $8.2 billion.','如今（2026 年 9 月）这些股票价值82亿美元。'),
                  ('Funding closed in February of this year.','融资在今年（2026 年）2月完成。')]
        for original,output in examples:
            with self.subTest(output=output):
                self.assertEqual(self.checks(original,output,self.source),[])
                self.assertTrue(self.checks(original,output,{}))
                self.assertTrue(compare(original,output,source=self.source)[1])
                self.assertTrue(self.checks(original,output.replace('2026','2025'),self.source))
        self.assertTrue(self.checks(examples[0][0],examples[0][1].replace('9 月','8 月'),self.source))

    def test_time_anchor_is_not_a_whitelist_for_arbitrary_dates_or_new_numbers(self):
        for original,output in [
            ('Shares are worth $8.2 billion.','如今（2026年9月）这些股票价值82亿美元。'),
            ('Now the value is $8.2 billion.','2026年9月29日价值82亿美元。'),
            ('Funding closed this year.','融资在今年（2026年）完成。另一笔融资在2026年完成。'),
            ('Funding closed this year.','融资在今年（2026年）完成，今年（2026年）又有一笔。'),
            ('Now it matters.','snow（2026年9月）有意义。'),
        ]:
            with self.subTest(output=output):self.assertTrue(self.checks(original,output,self.source))


class HygieneBoundaryRepairs(unittest.TestCase):
    def source(self,text):
        return source_record({'original_text':text,'source_language':'en','content_complete':True,
                             'author_name':'Duff','published_at':'2026-09-29T14:24:25+00:00'})

    def report(self,source,text,guidance=''):
        return postcheck(source,text,guidance,as_of='2026-10-02T12:00:00+00:00')

    def test_research_and_coverage_history_are_not_target_account_experience(self):
        cases=[('We study this risk.','我们通过出口管制来研究这一风险。'),
               ('In our data, returns fall.','在我们的数据中，回报率下降。'),
               ('I have been covering Micron.','自热潮开始以来，我一直在报道美光。'),
               ('Our previous report explained this.','我们此前的报告解释了这个问题。')]
        for original,output in cases:
            with self.subTest(output=output):
                source=self.source(original);before=copy.deepcopy(source)
                self.assertIn('possible_identity_transfer',{x['code'] for x in self.report(source,output)['findings']})
                self.assertEqual(source,before)
                for annotation in annotate(source)['annotations']:
                    if annotation['start'] is not None:
                        self.assertEqual(annotation['quote'],original[annotation['start']:annotation['end']])

    def test_correct_local_attribution_and_ordinary_judgment_are_preserved(self):
        source=self.source('Our research explains the risk.')
        for output in ('Duff said, "Our research explains the risk."','作者提到：“我们的研究解释了风险。”',
                       'I think this matters. We expect prices to rise.','我认为这很重要，我们预计价格会上涨。'):
            with self.subTest(output=output):
                self.assertNotIn('possible_identity_transfer',{x['code'] for x in self.report(source,output)['findings']})

    def test_chinese_author_in_previous_sentence_does_not_license_our_research(self):
        result=self.report(self.source('Our research matters.'),'Duff说市场变了。我们的研究证明这点。')
        self.assertIn('possible_identity_transfer',{x['code'] for x in result['findings']})

    def test_editorial_guidance_research_identity_is_checked_separately(self):
        result=self.report(self.source('We study this risk.'),'作者提到：“我们的研究关注这一风险。”',
                           'Keep the first-person research description.')
        self.assertTrue(any(x['code']=='guidance_identity_boundary' and x['location']=='editorial_guidance' for x in result['findings']))

    def test_missing_media_or_promised_continuation_flags_do_not_edit_copy(self):
        source=self.source('Both architectures are illustrated below. Here we explain the details.')
        text='两种架构均可见于下文。这里我们将解释细节。'
        result=self.report(source,text)
        self.assertTrue({'media_or_thread_reference','content_continuation_reference'}<={x['code'] for x in result['findings']})
        self.assertNotIn('replacement',result)

    def test_following_conditions_are_not_a_next_post_reference(self):
        source=self.source('The following conditions must all hold.')
        self.assertNotIn('media_or_thread_reference',{x['code'] for x in self.report(source,'以下条件必须全部成立。')['findings']})
        self.assertIn('media_or_thread_reference',{x['code'] for x in self.report(source,'下一条继续解释。')['findings']})

    def test_source_supported_spaced_year_anchor_is_not_stale_time(self):
        source=self.source('Funding closed in January of this year.')
        self.assertNotIn('stale_time_reference',{x['code'] for x in self.report(source,'融资在今年（2026 年）1月完成。')['findings']})
        self.assertIn('stale_time_reference',{x['code'] for x in self.report(source,'融资在今年（2025 年）1月完成。')['findings']})
        self.assertIn('stale_time_reference',{x['code'] for x in self.report(source,'融资在今年1月完成。')['findings']})


if __name__=='__main__':unittest.main()
