"""Regression tests for the comparison gate and the leaks it shipped alongside.

Every case here is a real one. The two comparison defects were written by the pipeline, passed all
seven gate layers, were queued as `ready_for_queue`, and were found by an outside judge reading
the pieces blind. The leak cases shipped in the same batch.

The negative cases matter as much as the positive ones. A gate that also fires on correct writing
gets relaxed or bypassed within a week, so each blocking rule is pinned against sentences that
must stay silent.
"""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qa.comparison import check_sentence
from qa.gates import _fact_positions
from content.leak_check import check as leak_check
from live.resolve_event import SENT

EPS = [{'id': 'g008', 'value': 2.46, 'unit': 'USD', 'label': 'GAAP EPS'},
       {'id': 'g009', 'value': 2.22, 'unit': 'USD', 'label': 'non-GAAP EPS'}]
PAYROLL = [{'id': 'p1', 'value': 162000, 'unit': 'persons', 'label': 'August payroll'},
           {'id': 'p2', 'value': 31000, 'unit': 'persons', 'label': '12-month mean'}]


def findings(text, facts):
    return check_sentence(text, facts, _fact_positions(text, facts))


def codes(text, facts):
    return sorted(x['code'] for x in findings(text, facts))


class ComparisonRunsTheWrongWay(unittest.TestCase):
    def test_slowdown_asserted_against_a_smaller_baseline(self):
        """Shipped. 16.2万 exceeds the 3.1万 baseline, so it is not a slowdown."""
        t = ('8 月非农就业增加 16.2 万人，这一数字虽看似稳健，但结合此前 12 个月月均 '
             '3.1 万人的背景，实际增速已显著放缓。')
        self.assertIn('contradicted_comparison', codes(t, PAYROLL))

    def test_the_finding_names_both_figures(self):
        t = '8 月非农就业增加 16.2 万人，结合此前 12 个月月均 3.1 万人，增速已显著放缓。'
        d = [x for x in findings(t, PAYROLL) if x['code'] == 'contradicted_comparison'][0]
        self.assertIn('162000', d['detail'])
        self.assertIn('31000', d['detail'])

    def test_correct_direction_is_silent(self):
        t = '8 月非农就业增加 16.2 万人，高于此前 12 个月月均 3.1 万人。'
        self.assertEqual([], codes(t, PAYROLL))

    def test_english_correct_direction_is_silent(self):
        t = 'Non-GAAP earnings of 2.22 dollars came in below the GAAP 2.46 dollars.'
        self.assertEqual([], codes(t, EPS))

    def test_stating_two_figures_without_comparing_is_silent(self):
        t = ('GAAP earnings per diluted share hit 2.46 dollars, while non-GAAP earnings per '
             'diluted share came in at 2.22 dollars.')
        self.assertEqual([], codes(t, EPS))

    def test_a_figures_own_movement_is_not_a_comparison(self):
        """"grew 18 percent" states no relation between two quantities."""
        t = 'Revenue grew 18 percent in the quarter.'
        self.assertEqual([], codes(t, [{'id': 'g', 'value': 18, 'unit': 'percent', 'label': 'g'}]))

    def test_unlike_units_are_not_ordered(self):
        """A dollar figure is not greater or less than a percentage."""
        mixed = [{'id': 'a', 'value': 96.2, 'unit': 'USD', 'label': 'revenue'},
                 {'id': 'b', 'value': 106, 'unit': 'percent', 'label': 'growth'}]
        t = 'Revenue of 96.2 dollars is above 106 percent.'
        self.assertEqual([], codes(t, mixed))


class ConditionsAreProposalsNotAssertions(unittest.TestCase):
    """This gate's own first false positive, kept so it cannot return.

    An invalidation condition orders two figures the way the writer expects them *not* to be, so
    reading it as an assertion reports correct writing as contradictory.
    """

    RANGE = [{'id': 'g010', 'value': 2, 'unit': 'percent', 'label': 'inflation level'},
             {'id': 'r002', 'value': 1.1, 'unit': 'percent', 'label': 'range floor'}]

    def test_an_invalidation_condition_is_not_an_assertion(self):
        t = 'I would be wrong if the 2 percent level falls below the 1.1 percent range.'
        self.assertEqual([], codes(t, self.RANGE))

    def test_marked_condition_sentences_are_skipped_whole(self):
        t = 'The 2 percent level falls below the 1.1 percent range.'
        pos = _fact_positions(t, self.RANGE)
        self.assertEqual([], check_sentence(t, self.RANGE, pos, kind='condition'))

    def test_chinese_condition(self):
        facts = [{'id': 'a', 'value': 162000, 'unit': 'persons', 'label': 'payroll'},
                 {'id': 'b', 'value': 31000, 'unit': 'persons', 'label': 'mean'}]
        t = '若 16.2 万人的月增回落到低于 3.1 万人，这个判断就不成立。'
        self.assertEqual([], codes(t, facts))

    def test_a_fact_clause_before_a_condition_is_still_checked(self):
        facts = [{'id': 'a', 'value': 162000, 'unit': 'persons', 'label': 'payroll'},
                 {'id': 'b', 'value': 31000, 'unit': 'persons', 'label': 'mean'}]
        t = '8 月新增 16.2 万人，较月均 3.1 万人明显放缓，如果后续回落则另当别论。'
        self.assertIn('contradicted_comparison', codes(t, facts))


class ComparisonWithoutABaseline(unittest.TestCase):
    def test_outpaced_an_uncited_baseline(self):
        """Shipped. The 2.46 GAAP figure is in the piece but not in this sentence's citations."""
        t = ('Non-GAAP earnings per diluted share of 2.22 dollars outpaced GAAP figures, '
             'highlighting the impact of one-time charges.')
        self.assertIn('comparison_without_baseline', codes(t, [EPS[1]]))

    def test_a_baseline_carried_in_words_is_allowed(self):
        """"than a year ago" names a baseline the pack holds as a growth rate, not a level."""
        t = 'Data Center revenue of 89 dollars is higher than a year ago.'
        self.assertEqual([], codes(t, [{'id': 'g004', 'value': 89, 'unit': 'USD', 'label': 'DC'}]))

    def test_no_figure_at_all_is_not_this_gates_business(self):
        t = 'Momentum slowed through the quarter.'
        self.assertEqual([], codes(t, EPS))


class PromptArtefactsThatShipped(unittest.TestCase):
    def test_mask_marker_glued_into_a_quotation(self):
        """Shipped inside a quoted notepad line as "$5a figure bil."."""
        t = 'Bessent\'s notepad read, "Buy Japanese Yen (JPY) $5a figure bil." That is the story.'
        got = [x['code'] for x in leak_check(t)['findings']]
        self.assertIn('mask_marker_in_output', got)

    def test_mask_marker_read_as_prose(self):
        t = 'The yen jumped more than 2% against the greenback, touching a figure per dollar today.'
        got = [x['code'] for x in leak_check(t)['findings']]
        self.assertIn('mask_marker_in_output', got)

    def test_reference_to_the_slot_table(self):
        t = ('The strongest reading against this view is that the table contains no consensus '
             'forecasts, so the growth rate cannot be verified here.')
        got = [x['code'] for x in leak_check(t)['findings']]
        self.assertIn('prompt_furniture_in_output', got)

    def test_reference_to_a_chart_that_does_not_exist(self):
        t = 'Inflation expectations have risen to around 2 percent, as suggested by Chart a figure.'
        got = [x['code'] for x in leak_check(t)['findings']]
        self.assertIn('prompt_furniture_in_output', got)

    def test_ordinary_prose_about_a_figure_is_untouched(self):
        """"a figure" is ordinary English; only a figure-shaped use of it is a leak."""
        t = ('Revenue reached 96.2 billion dollars this quarter, a figure that few analysts had '
             'modelled at the start of the year.')
        got = [x['code'] for x in leak_check(t)['findings']]
        self.assertNotIn('mask_marker_in_output', got)
        self.assertNotIn('prompt_furniture_in_output', got)


class SentencesAreNotCutAtAbbreviations(unittest.TestCase):
    def test_us_abbreviation_no_longer_truncates(self):
        """Shipped as "a sharp 1% spike in the yen against the U." with the rest discarded."""
        t = ('The currency move follows a similar sharp 1% spike in the yen against the U.S. '
             'dollar in July.')
        self.assertEqual([t], [m.group().strip() for m in SENT.finditer(t)])

    def test_company_suffix_no_longer_eats_the_subject(self):
        t = 'Amazon.com Inc. reported net sales of $167.7 billion. Shares rose sharply.'
        got = [m.group().strip() for m in SENT.finditer(t)]
        self.assertTrue(got[0].startswith('Amazon.com Inc.'))

    def test_decimals_still_do_not_split(self):
        t = 'Revenue rose 3.5% in Q2. Operating income fell 1.2%.'
        self.assertEqual(2, len([m for m in SENT.finditer(t)]))

    def test_a_real_sentence_end_still_ends(self):
        t = 'Core CPI was 2.4%, per the BLS. That is the key number here.'
        self.assertEqual(2, len([m for m in SENT.finditer(t)]))


if __name__ == '__main__':
    unittest.main()


class CarryingOnlyCrossesBoundaries(unittest.TestCase):
    """CLAUDE.md: 搬运只能跨语言或跨平台，同语言同平台一律不准搬。

    The English draft that reproduced 43 tokens of its donor's post is the same-language case.
    The cross-language case is the Cross-language Information Gap lane working as specified: the
    facts move, the sentences are written in the target language.
    """

    DONOR_EN = ('The BOJ is reportedly leaning toward a 25-basis-point rate hike at its Sept 18 '
                'meeting, with inflation risks remaining. TAP IMAGE TO SEE FULL INSIGHT '
                'https://t.co/abc123')

    def test_same_language_carrying_is_blocked(self):
        from content.originality import check
        draft = ('The BOJ is reportedly leaning toward a 25-basis-point rate hike at its Sept 18 '
                 'meeting, with inflation risks remaining. That is the setup.')
        r = check(draft, 'en', exemplars=[self.DONOR_EN])
        self.assertEqual('failed', r['status'])
        self.assertIn('verbatim_from_donor', [x['code'] for x in r['findings']])

    def test_cross_language_carrying_is_allowed(self):
        from content.originality import check
        draft = ('日本央行可能在 9 月 18 日会议上加息 25 个基点，通胀压力仍在。'
                 '这对套息交易的影响比对国债更直接。')
        r = check(draft, 'zh', exemplars=[self.DONOR_EN])
        self.assertEqual('passed', r['status'])
        self.assertEqual(1, r['cross_language_pairs'])
        self.assertEqual(0, r['same_language_sources_compared'])

    def test_promotional_wording_is_blocked_across_the_boundary_too(self):
        from content.originality import check
        draft = '日本央行可能在 9 月 18 日加息 25 个基点。点击图片查看全文 https://t.co/abc123'
        r = check(draft, 'zh', exemplars=[self.DONOR_EN])
        got = [x['code'] for x in r['findings']]
        self.assertIn('promotional_boilerplate', got)
        self.assertIn('link_that_is_not_the_source', got)

    def test_the_source_document_may_be_linked(self):
        from content.originality import check
        url = 'https://investor.nvidia.com/news/press-release-details/2026/x'
        r = check(f'Revenue hit a record this quarter. Source: {url}', 'en', allowed_urls=[url])
        self.assertNotIn('link_that_is_not_the_source', [x['code'] for x in r['findings']])


class HedgedAttribution(unittest.TestCase):
    """"X 表明 Y" ties a figure to an inference without committing to it.

    Thresholds are per piece, at each language's p99 over the donors' own posts: 97.7% of their
    Chinese posts and 99.5% of their English posts contain none of these phrases.
    """

    def test_one_use_in_chinese_is_within_the_human_range(self):
        from content.tells import check
        t = ('8 月非农增加 16.2 万人，表明劳动力市场仍有韧性。但工时已经连续两个月回落。'
             '这不是一个可以放心的组合。我更担心的是工资端。下个月修订值会说明更多。')
        got = [x['code'] for x in check(t, 'zh')['findings'] if x['severity'] == 'blocking']
        self.assertNotIn('hedged_attribution', got)

    def test_two_uses_in_chinese_block(self):
        from content.tells import check
        t = ('8 月非农增加 16.2 万人，表明劳动力市场仍有韧性。工时回落反映出需求在走弱。'
             '这不是一个可以放心的组合。我更担心的是工资端。下个月修订值会说明更多。')
        got = [x['code'] for x in check(t, 'zh')['findings'] if x['severity'] == 'blocking']
        self.assertIn('hedged_attribution', got)

    def test_one_use_in_english_blocks(self):
        from content.tells import check
        t = ('Revenue grew 18% this quarter. The print highlights the strength of data centre '
             'demand. Margins held. I would want to see the backlog before calling it a trend. '
             'That is the part nobody has shown yet.')
        got = [x['code'] for x in check(t, 'en')['findings'] if x['severity'] == 'blocking']
        self.assertIn('hedged_attribution', got)

    def test_ordinary_chinese_connectives_are_not_banned(self):
        """意味着 (0.272/1000 chars) and 进一步 (0.350) are words the donors use constantly."""
        from content.tells import check
        t = ('8 月非农增加 16.2 万人，这意味着降息的紧迫性下降。工时进一步回落。'
             '我不认为这是转向。下个月修订值会说明更多。那才是关键的一期数据。')
        got = [x['code'] for x in check(t, 'zh')['findings'] if x['severity'] == 'blocking']
        self.assertNotIn('hedged_attribution', got)
