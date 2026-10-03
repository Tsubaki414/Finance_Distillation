"""Adversarial regression suite for the seven-layer QA gates.

Cases are constructed, not copied from the S1 draft, and the generalisation cases use numbers and
wording that never appear in it. Nothing here hardcodes a BLS filename or a Chinese phrase from the
failing case: the gates must catch the class of error, not the instance.

Run: .venv/bin/python -B tests/test_qa_gates.py
"""
from pathlib import Path
import sys, json, unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from content.generate_slotted import audit_numbers, collapse_duplicate_frames
from content.form_check import check as form_check
from content.fact_slots import render_value
from content import visuals
from qa.gates import (evaluate, layer2_numeric, layer2_percent_vs_pp, layer2_period,
                      layer3_entailment, layer4_citation, layer5_fact_selection,
                      layer6_clause_attachment, layer6_sign_direction, layer7_status,
                      parse_numbers, BLOCKING)

PACKET = json.loads((ROOT / 'evidence_loop/sources/packets/75155f58f5a995e3.json').read_text())
ALLOWED = {f['id']: f for f in PACKET['facts']}


def sent(text, ids, kind='fact', sid='s1'):
    return {'sentence_id': sid, 'text': text, 'kind': kind, 'fact_ids': ids}


def case(sentences):
    return {'sentence_to_source_ledger': sentences}


def codes(findings):
    return {f['code'] for f in findings}


def blocking(result):
    return [f for f in result['findings'] if f['severity'] == BLOCKING]


class NumberParsing(unittest.TestCase):
    def test_chinese_scale_words(self):
        v = {n['text']: n['value'] for n in parse_numbers('上修 4.4 万，另一处 0.44 万，还有 1.2 亿')}
        self.assertAlmostEqual(v['4.4 万'], 44000)
        self.assertAlmostEqual(v['0.44 万'], 4400)
        self.assertAlmostEqual(v['1.2 亿'], 120000000)

    def test_english_scale_words(self):
        v = {n['text'].lower(): n['value'] for n in parse_numbers('revenue of 2.3 billion and 44 thousand jobs')}
        self.assertAlmostEqual(v['2.3 billion'], 2.3e9)
        self.assertAlmostEqual(v['44 thousand'], 44000)


class Layer2Magnitude(unittest.TestCase):
    """Case 1 and 2: the exact defect that shipped, and its correct form."""

    def test_1_magnitude_slip_fails(self):
        fx = [ALLOWED['revision_previous']]
        f = layer2_numeric('7 月数据上修 0.44 万', fx)
        self.assertIn('numeric_magnitude', codes(f))

    def test_2_correct_magnitude_passes(self):
        fx = [ALLOWED['revision_previous']]
        f = layer2_numeric('7 月数据上修 4.4 万', fx)
        self.assertEqual(codes(f), set())

    def test_9_right_number_wrong_period_fails(self):
        fx = [ALLOWED['payroll']]
        f = layer2_period('2026 年 6 月非农就业新增 16.2 万人', fx)
        self.assertIn('period_mismatch', codes(f))

    def test_9b_right_number_right_period_passes(self):
        fx = [ALLOWED['payroll']]
        self.assertEqual(codes(layer2_period('2026 年 8 月非农就业新增 16.2 万人', fx)), set())

    def test_10_percent_vs_percentage_point_fails(self):
        fx = [ALLOWED['participation_since_jan']]   # 0.5, unit percentage
        f = layer2_percent_vs_pp('劳动参与率较一月下降 0.5%', fx)
        self.assertIn('percent_vs_percentage_point', codes(f))

    def test_10b_correct_percentage_point_passes(self):
        fx = [ALLOWED['participation_since_jan']]
        self.assertEqual(codes(layer2_percent_vs_pp('劳动参与率较一月下降 0.5 个百分点', fx)), set())


class Layer3Entailment(unittest.TestCase):
    def test_3_consensus_claim_without_source_fails(self):
        f = layer3_entailment('时薪环比增长 0.3%，高于市场预期', [ALLOWED['ahe_mom']], PACKET)
        self.assertIn('out_of_evidence_assertion', codes(f))

    def test_3b_consensus_claim_with_verified_source_passes(self):
        f = layer3_entailment('时薪环比增长 0.3%，高于市场预期', [ALLOWED['ahe_mom']], PACKET,
                              extra_sources={'consensus': {'provider': 'verified estimate feed',
                                                           'value': 0.2}})
        self.assertNotIn('out_of_evidence_assertion', codes(f))

    def test_english_consensus_phrasing_also_caught(self):
        f = layer3_entailment('Average hourly earnings beat consensus', [ALLOWED['ahe_mom']], PACKET)
        self.assertIn('out_of_evidence_assertion', codes(f))


class Layer4Citation(unittest.TestCase):
    def test_4_level_cited_for_change_fails(self):
        f = layer4_citation('周工时微增', ['workweek'], ALLOWED)
        self.assertIn('citation_relation_mismatch', codes(f))
        self.assertEqual([x for x in f if x['code'] == 'citation_relation_mismatch'][0]['should_cite'],
                         'workweek_change')

    def test_4b_change_cited_for_change_passes(self):
        self.assertEqual(codes(layer4_citation('周工时微增', ['workweek_change'], ALLOWED)), set())

    def test_8_citation_exists_but_does_not_entail(self):
        """Case 8: the ID is valid and the relation is a change, but no cited fact is a change."""
        f = layer4_citation('长期失业占比较上月明显上升', ['long_term_share'], ALLOWED)
        self.assertIn('citation_relation_mismatch', codes(f))

    def test_unknown_id_fails(self):
        self.assertIn('unknown_fact_id', codes(layer4_citation('随便', ['not_a_fact'], ALLOWED)))


class Layer5Selection(unittest.TestCase):
    MUST = ['payroll', 'participation', 'part_time_decline']

    def test_6_missing_mandatory_fact_fails(self):
        led = [sent('非农新增 16.2 万人', ['payroll'])]
        f, m = layer5_fact_selection(led, self.MUST, [], ALLOWED)
        self.assertIn('must_include_missing', codes(f))
        self.assertIn('part_time_decline', [x for x in f if x['code'] == 'must_include_missing'][0]['detail'])

    def test_7_missing_optional_fact_does_not_fail(self):
        led = [sent('a', ['payroll']), sent('b', ['participation']), sent('c', ['part_time_decline'])]
        f, m = layer5_fact_selection(led, self.MUST, [], ALLOWED)
        self.assertEqual(codes(f), set())
        self.assertEqual(m['must_include_coverage'], 1.0)
        self.assertLess(m['all_fact_coverage'], 1.0)   # optional facts absent, still passing

    def test_plan_required_enforced(self):
        led = [sent('a', ['payroll'])]
        f, _ = layer5_fact_selection(led, [], ['ahe_yoy'], ALLOWED)
        self.assertIn('plan_required_missing', codes(f))

    def test_fact_outside_evidence_set_fails(self):
        led = [sent('a', ['payroll', 'made_up_fact'])]
        f, _ = layer5_fact_selection(led, [], [], ALLOWED)
        self.assertIn('fact_outside_evidence_set', codes(f))


class Layer6Attachment(unittest.TestCase):
    def test_5_overall_number_attached_to_sector_fails(self):
        """payroll_12m_mean is a whole-economy mean placed right after a sector name."""
        f = layer6_clause_attachment('信息业持续收缩，此前 12 个月月均仅 3.1 万',
                                     ['payroll_12m_mean'], ALLOWED)
        self.assertIn('clause_attribution', codes(f))

    def test_5b_sector_fact_next_to_sector_passes(self):
        f = layer6_clause_attachment('信息业此前 12 个月平均月变化为 -0.8 万',
                                     ['information_12m_mean'], ALLOWED)
        self.assertEqual(codes(f), set())

    def test_5c_overall_number_far_from_sector_passes(self):
        f = layer6_clause_attachment('整体非农此前 12 个月月均 3.1 万，另外我们也观察了很多其他方面的结构性问题以及行业层面的分化情况，比如信息业',
                                     ['payroll_12m_mean'], ALLOWED)
        self.assertEqual(codes(f), set())


class Layer7Status(unittest.TestCase):
    def test_blocking_forces_blocked(self):
        st = layer7_status([{'severity': BLOCKING, 'code': 'x'}])
        self.assertEqual(st['qa_status'], 'failed')
        self.assertEqual(st['content_status'], 'blocked')

    def test_clean_is_ready(self):
        st = layer7_status([])
        self.assertEqual(st['qa_status'], 'passed')
        self.assertEqual(st['content_status'], 'ready_for_pipeline')

    def test_warning_alone_does_not_block(self):
        st = layer7_status([{'severity': 'warning', 'code': 'x'}])
        self.assertEqual(st['content_status'], 'ready_for_pipeline')


class Case11Generalisation(unittest.TestCase):
    """Case 11: errors that never appear in the S1 draft, using different facts and wording."""

    def test_novel_magnitude_error_on_a_different_fact(self):
        # discouraged = 441,000. Write it as 4.41 万 (=44,100), a 10x slip on an unused fact.
        f = layer2_numeric('放弃求职者 4.41 万人', [ALLOWED['discouraged']])
        self.assertIn('numeric_magnitude', codes(f))

    def test_novel_english_magnitude_error(self):
        f = layer2_numeric('marginal attachment stood at 17 thousand', [ALLOWED['marginal_attachment']])
        self.assertIn('numeric_magnitude', codes(f))

    def test_novel_record_claim_is_blocked(self):
        f = layer3_entailment('医疗保健就业创纪录', [ALLOWED['health']], PACKET)
        self.assertIn('unsupported_relation', codes(f))

    def test_novel_priced_in_claim_is_blocked(self):
        f = layer3_entailment('市场已经定价了这一结果', [ALLOWED['payroll']], PACKET)
        self.assertIn('unsupported_relation', codes(f))

    def test_novel_sector_attachment_with_different_sector(self):
        f = layer6_clause_attachment('制造业疲弱，整体月均 3.1 万', ['payroll_12m_mean'], ALLOWED)
        self.assertIn('clause_attribution', codes(f))

    def test_novel_period_error_on_wage_fact(self):
        f = layer2_period('2026 年 3 月平均时薪环比 0.3%', [ALLOWED['ahe_mom']])
        self.assertIn('period_mismatch', codes(f))


class EndToEnd(unittest.TestCase):
    def test_clean_draft_reaches_ready(self):
        led = [
            sent('2026 年 8 月非农就业新增 16.2 万人', ['payroll'], sid='s1'),
            sent('劳动参与率为 61.6%', ['participation'], sid='s2'),
            sent('因经济原因从事兼职的人数减少 41.4 万人', ['part_time_decline'], sid='s3'),
        ]
        r = evaluate(case(led), PACKET, must_include=['payroll', 'participation', 'part_time_decline'])
        self.assertEqual(blocking(r), [], f'unexpected: {blocking(r)}')
        self.assertEqual(r['status']['content_status'], 'ready_for_pipeline')

    def test_defective_draft_is_blocked_with_multiple_layers(self):
        led = [
            sent('7 月数据上修 0.44 万', ['revision_previous'], sid='s1'),
            sent('时薪环比 0.3%，高于市场预期', ['ahe_mom'], sid='s2'),
            sent('周工时微增', ['workweek'], sid='s3'),
            sent('信息业持续收缩，此前 12 个月月均仅 3.1 万', ['payroll_12m_mean'], sid='s4'),
        ]
        r = evaluate(case(led), PACKET, must_include=['payroll', 'part_time_decline'])
        c = codes(r['findings'])
        for expected in ('numeric_magnitude', 'out_of_evidence_assertion',
                         'citation_relation_mismatch', 'clause_attribution', 'must_include_missing'):
            self.assertIn(expected, c, f'{expected} not detected')
        self.assertEqual(r['status']['content_status'], 'blocked')

    def test_layer1_detects_a_tampered_fact_pack(self):
        src = (ROOT / 'evidence_loop' / PACKET['artifact_path']).read_text()
        bad = json.loads(json.dumps(PACKET))
        bad['facts'][0]['source_span']['quote'] = 'this string is not in the source'
        r = evaluate(case([]), bad, source_text=src)
        self.assertIn('span_does_not_match_source', codes(r['findings']))

    def test_layer1_passes_on_the_real_packet(self):
        src = (ROOT / 'evidence_loop' / PACKET['artifact_path']).read_text()
        r = evaluate(case([]), PACKET, source_text=src)
        span_issues = [f for f in r['findings'] if f['layer'] == 1]
        self.assertEqual(span_issues, [], f'real packet should be faithful: {span_issues[:3]}')
        self.assertEqual(r['metrics']['source_fact_accuracy'], 1.0)


class FalsePositiveGuards(unittest.TestCase):
    """Patterns the first v2 smoke run showed the gates flagging wrongly.

    A gate that blocks correct prose is worse than no gate, so each of these must pass clean.
    """

    def test_comparison_baseline_month_is_not_a_period_error(self):
        f = layer2_period('劳动参与率虽升至 61.6%，但较 1 月下降 0.5 个百分点',
                          [ALLOWED['participation'], ALLOWED['participation_since_jan']])
        self.assertEqual(codes(f), set())

    def test_revision_sentence_may_name_the_revised_months(self):
        f = layer2_period('6 月与 7 月数据分别上修 1.1 万和 4.4 万人，合计 5.5 万人',
                          [ALLOWED['revision_prior'], ALLOWED['revision_total']])
        self.assertEqual(codes(f), set())

    def test_forward_looking_condition_is_not_a_period_error(self):
        f = layer2_period('但需警惕若 9 月 CPI 反弹或失业率显著上升，将推翻当前假设',
                          [ALLOWED['ahe_yoy'], ALLOWED['unemployment_rate']])
        self.assertEqual(codes(f), set())

    def test_hypothetical_change_does_not_need_a_change_citation(self):
        f = layer4_citation('若 9 月失业率显著上升，将推翻当前假设',
                            ['unemployment_rate'], ALLOWED)
        self.assertEqual(codes(f), set())

    def test_real_period_error_still_fails_after_the_guards(self):
        f = layer2_period('2026 年 6 月非农就业新增 16.2 万人', [ALLOWED['payroll']])
        self.assertIn('period_mismatch', codes(f))

    def test_real_change_miscitation_still_fails_after_the_guards(self):
        f = layer4_citation('制造业周工时增至 40.5 小时', ['manufacturing_workweek'], ALLOWED)
        self.assertIn('citation_relation_mismatch', codes(f))


class SmokeRunFalsePositives(unittest.TestCase):
    """Patterns the 15-cell smoke run flagged wrongly. Seven cells failed on the same one."""

    def test_duration_phrase_is_not_a_figure(self):
        # "12 个月" parsed as 12 and compared against food_12m_mean=12,000 gave a false 1000x.
        f = layer2_numeric('餐饮与酒吧就业月增 5.9 万，显著高于此前 12 个月的平均月增 1.2 万',
                           [ALLOWED['food'], ALLOWED['food_12m_mean']])
        self.assertEqual(codes(f), set(), f'unexpected: {f}')

    def test_english_duration_phrase_is_not_a_figure(self):
        f = layer2_numeric('averaged over the prior 12 months', [ALLOWED['food_12m_mean']])
        self.assertEqual(codes(f), set())

    def test_hypothetical_consensus_reference_is_allowed(self):
        f = layer3_entailment('若 9 月非农大幅低于预期，软着陆假设将被证伪',
                              [ALLOWED['payroll']], PACKET)
        self.assertEqual(codes(f), set())

    def test_hypothetical_proof_word_is_allowed(self):
        f = layer3_entailment('若 8 月 CPI 显著反弹，证明通胀粘性，则降息预期将被削弱',
                              [ALLOWED['ahe_yoy']], PACKET)
        self.assertEqual(codes(f), set())

    def test_asserted_consensus_still_fails(self):
        f = layer3_entailment('时薪环比 0.3%，高于市场预期', [ALLOWED['ahe_mom']], PACKET)
        self.assertIn('out_of_evidence_assertion', codes(f))

    def test_real_magnitude_error_still_fails_with_duration_present(self):
        f = layer2_numeric('过去 12 个月中，7 月上修 0.44 万', [ALLOWED['revision_previous']])
        self.assertIn('numeric_magnitude', codes(f))


class ConditionalScopeLayer4(unittest.TestCase):
    def test_conditional_governs_later_clauses_in_layer4(self):
        f = layer4_citation('若 9 月非农大幅低于预期，或失业率升至 4.5% 以上，软着陆假设将被证伪',
                            ['payroll', 'unemployment_rate'], ALLOWED)
        self.assertEqual(codes(f), set(), f'unexpected: {f}')

    def test_asserted_change_outside_a_conditional_still_fails(self):
        f = layer4_citation('失业率升至 4.5%', ['unemployment_rate'], ALLOWED)
        self.assertIn('citation_relation_mismatch', codes(f))


class DisclaimerAndSubjectScope(unittest.TestCase):
    """From the first slot-constrained draft: a denial is not an assertion, and a change word
    only matters when it attaches to a cited fact's subject."""

    def test_negated_relation_is_not_an_assertion(self):
        f = layer3_entailment('季节调整后行业增长并非因果机制的证明',
                              [ALLOWED['information']], PACKET)
        self.assertEqual(codes(f), set(), f'unexpected: {f}')

    def test_asserted_proof_still_fails(self):
        f = layer3_entailment('这组数据证明经济已经进入衰退', [ALLOWED['payroll']], PACKET)
        self.assertIn('unsupported_relation', codes(f))

    def test_change_word_on_another_subject_is_ignored(self):
        f = layer4_citation('劳动参与率为 61.6%，表明工资增长可能受到制约',
                            ['participation'], ALLOWED)
        self.assertEqual(codes(f), set(), f'unexpected: {f}')

    def test_change_asserted_about_the_cited_fact_still_fails(self):
        f = layer4_citation('劳动参与率降至 61.6%', ['participation'], ALLOWED)
        self.assertIn('citation_relation_mismatch', codes(f))


class FlowDirection(unittest.TestCase):
    """A passing draft stated the direction of labour movement backwards."""

    def test_reversed_direction_fails(self):
        from qa.gates import layer6_flow_direction
        f = layer6_flow_direction('信息业就业减少 2.3 万人，餐饮与酒吧就业增加 5.9 万人，'
                                  '显示出劳动力正在从传统服务业向科技部门转移',
                                  [ALLOWED['information'], ALLOWED['food']])
        self.assertIn('flow_direction_reversed', codes(f))

    def test_correct_direction_passes(self):
        from qa.gates import layer6_flow_direction
        f = layer6_flow_direction('劳动力正在从科技部门向传统服务业转移',
                                  [ALLOWED['information'], ALLOWED['food']])
        self.assertEqual(codes(f), set())

    def test_no_flow_claim_is_ignored(self):
        from qa.gates import layer6_flow_direction
        f = layer6_flow_direction('信息业就业减少 2.3 万人', [ALLOWED['information']])
        self.assertEqual(codes(f), set())


if __name__ == '__main__':
    unittest.main(verbosity=2)


class ProposedThresholds(unittest.TestCase):
    """An invalidation condition has to name a threshold. The writer's proposed figure is
    allowed but must stay labelled as a proposal, never as a sourced number."""

    SLOTS = [{'slot_id': 'S01', 'value_rendered': '16.2 万人', 'rendered': '8 月非农就业增加 16.2 万人'},
             {'slot_id': 'S02', 'value_rendered': '4.3%', 'rendered': '失业率为 4.3%'}]

    def test_threshold_in_condition_is_proposed_not_invented(self):
        used, invented, proposed, _ = audit_numbers(
            '失效条件为失业率反弹至 4.6% 以上。', self.SLOTS, kind='condition')
        self.assertEqual(invented, [])
        self.assertIn('4.6%', proposed)

    def test_ruo_clause_threshold_is_proposed(self):
        _, invented, proposed, _ = audit_numbers(
            '若非农连续两月低于 10 万人，这个判断就不成立。', self.SLOTS, kind='condition')
        self.assertEqual(invented, [])
        self.assertIn('10 万人', proposed)

    def test_off_table_number_outside_the_clause_still_fails(self):
        _, invented, proposed, _ = audit_numbers(
            '制造业裁员 9.9 万人，若失业率升至 4.6% 以上则判断失效。', self.SLOTS, kind='condition')
        self.assertIn('9.9 万人', invented)
        self.assertIn('4.6%', proposed)

    def test_a_factual_sentence_gets_no_exemption(self):
        _, invented, proposed, _ = audit_numbers(
            '失业率为 4.6%。', self.SLOTS, kind='fact')
        self.assertIn('4.6%', invented)
        self.assertEqual(proposed, [])

    def test_slot_values_are_still_credited_inside_a_condition(self):
        used, invented, _, _ = audit_numbers(
            '若后续非农低于本月的 16.2 万人则失效。', self.SLOTS, kind='condition')
        self.assertIn('S01', used)
        self.assertEqual(invented, [])

    def test_form_check_surfaces_the_proposal(self):
        rows = [{'sentence_id': 's9', 'text': '若失业率升至 4.6% 以上则失效。', 'kind': 'condition',
                 'proposed_thresholds': ['4.6%'], 'slot_ids': [], 'model_written_digits': []}]
        out = form_check('若失业率升至 4.6% 以上则失效。', rows, self.SLOTS)
        codes = [f['code'] for f in out['findings']]
        self.assertIn('author_proposed_threshold', codes)
        self.assertEqual(
            [f['severity'] for f in out['findings'] if f['code'] == 'author_proposed_threshold'],
            ['warning'])


class SignDirection(unittest.TestCase):
    """The renderer prints a magnitude and carries the direction in the frame, so a draft that
    supplies its own wording can reverse the sign while keeping the number correct."""

    INFO = {'id': 'information', 'label': '信息业就业月变化', 'value': -23000, 'unit': 'persons',
            'period': '2026-08', 'source_block_ids': ['b1']}
    HEALTH = {'id': 'health', 'label': '医疗保健就业月增量', 'value': 13000, 'unit': 'persons',
              'period': '2026-08', 'source_block_ids': ['b1']}
    PART_TIME = {'id': 'part_time_decline', 'label': '经济原因兼职人数减少', 'value': 414000,
                 'unit': 'persons_decline', 'period': '2026-08', 'source_block_ids': ['b1']}

    def test_declining_sector_called_an_engine_of_growth(self):
        out = layer6_sign_direction(
            '信息业就业月变化 2.3 万人构成了就业增长的主要引擎', [self.INFO])
        self.assertEqual([x['code'] for x in out], ['sign_direction_mismatch'])
        self.assertEqual(out[0]['severity'], 'blocking')

    def test_declining_sector_described_as_a_decline_passes(self):
        self.assertEqual(
            layer6_sign_direction('信息业就业减少 2.3 万人，拖累了整体表现', [self.INFO]), [])

    def test_positive_sector_called_a_contraction(self):
        out = layer6_sign_direction('医疗保健就业月增量 1.3 万人正在收缩', [self.HEALTH])
        self.assertEqual([x['code'] for x in out], ['sign_direction_mismatch'])

    def test_decline_unit_counts_as_declining_even_when_value_is_positive(self):
        out = layer6_sign_direction('经济原因兼职人数 41.4 万人仍在增加', [self.PART_TIME])
        self.assertEqual([x['code'] for x in out], ['sign_direction_mismatch'])

    def test_uncited_fact_is_not_judged(self):
        self.assertEqual(layer6_sign_direction('制造业就业增长强劲', [self.INFO]), [])

    def test_clause_without_the_facts_number_is_out_of_scope(self):
        """This layer judges "number present, direction wrong". A clause with no figure is left
        to the citation and entailment layers, because 增量 there usually belongs to another fact."""
        self.assertEqual(layer6_sign_direction('信息业的调整仍在扩张周期内', [self.INFO]), [])

    def test_clause_scope_keeps_a_correct_neighbour_clean(self):
        out = layer6_sign_direction(
            '信息业就业减少 2.3 万人，医疗保健就业月增量 1.3 万人继续扩张',
            [self.INFO, self.HEALTH])
        self.assertEqual(out, [])


class MisframedInlineValues(unittest.TestCase):
    SLOTS = [{'slot_id': 'S01', 'value_rendered': '2.3 万人', 'direction_word': '减少',
              'rendered': '信息业就业减少 2.3 万人'},
             {'slot_id': 'S02', 'value_rendered': '4.1%', 'direction_word': None,
              'rendered': '失业率为 4.1%'}]

    def test_value_without_its_direction_word_is_not_credited(self):
        used, _, _, mis = audit_numbers('信息业就业月变化 2.3 万人', self.SLOTS)
        self.assertEqual(used, [])
        self.assertEqual(mis[0]['slot_id'], 'S01')
        self.assertEqual(mis[0]['missing_direction_word'], '减少')

    def test_value_with_its_direction_word_is_credited(self):
        used, _, _, mis = audit_numbers('信息业就业减少 2.3 万人', self.SLOTS)
        self.assertEqual(used, ['S01'])
        self.assertEqual(mis, [])

    def test_a_level_fact_needs_no_direction_word(self):
        used, _, _, mis = audit_numbers('失业率为 4.1%', self.SLOTS)
        self.assertEqual(used, ['S02'])
        self.assertEqual(mis, [])

    def test_form_check_blocks_on_a_misframed_value(self):
        rows = [{'sentence_id': 's4', 'text': '信息业就业月变化 2.3 万人', 'kind': 'fact',
                 'slot_ids': [], 'model_written_digits': [],
                 'misframed_values': [{'slot_id': 'S01', 'value': '2.3万人',
                                       'missing_direction_word': '减少'}]}]
        out = form_check('信息业就业月变化 2.3 万人', rows, self.SLOTS)
        self.assertIn('direction_word_dropped', [x['code'] for x in out['findings']])
        self.assertEqual(out['form_status'], 'failed')


class DuplicateFrames(unittest.TestCase):
    SLOTS = [{'slot_id': 'S08', 'value_rendered': '5.5 万人',
              'rendered': '前两个月合计上修 5.5 万人', 'direction_word': '上修'}]

    def test_frame_written_twice_is_collapsed(self):
        out = collapse_duplicate_frames('前两个月合计上修 前两个月合计上修 5.5 万人。', self.SLOTS)
        self.assertEqual(out, '前两个月合计上修 5.5 万人。')

    def test_a_single_frame_is_left_alone(self):
        self.assertEqual(
            collapse_duplicate_frames('前两个月合计上修 5.5 万人。', self.SLOTS),
            '前两个月合计上修 5.5 万人。')


class SignDirectionLevelFacts(unittest.TestCase):
    """A level has no direction. Treating 劳动参与率 61.6% as "positive, therefore growth" made
    the gate reject two correct sentences about the labour market shrinking."""

    PARTICIPATION = {'id': 'participation', 'label': '劳动参与率', 'value': 61.6,
                     'unit': 'percent', 'period': '2026-08', 'source_block_ids': ['b1']}
    PAYROLL = {'id': 'payroll', 'label': '非农就业月增量', 'value': 162000, 'unit': 'persons',
               'period': '2026-08', 'source_block_ids': ['b1']}

    def test_level_fact_with_a_decline_word_is_not_a_contradiction(self):
        self.assertEqual(layer6_sign_direction(
            '劳动参与率 61.6% 之下，劳动力市场可能正在经历隐性收缩', [self.PARTICIPATION]), [])

    def test_change_fact_with_the_wrong_direction_still_blocks(self):
        out = layer6_sign_direction('非农就业月增量 16.2 万人显示岗位在流失', [self.PAYROLL])
        self.assertEqual([x['code'] for x in out], ['sign_direction_mismatch'])


class SignDirectionScope(unittest.TestCase):
    """A direction word belongs to the fact it sits against, not to every fact in the clause."""

    PART_SINCE_JAN = {'id': 'participation_since_jan', 'label': '劳动参与率较一月下降幅度',
                      'value': 0.5, 'unit': 'percentage_points_decline', 'period': '2026-08',
                      'source_block_ids': ['b1']}
    INFO = {'id': 'information', 'label': '信息业就业月变化', 'value': -23000, 'unit': 'persons',
            'period': '2026-08', 'source_block_ids': ['b1']}

    def test_growth_word_belonging_to_another_fact_is_not_charged(self):
        self.assertEqual(layer6_sign_direction(
            '修正与参与率改变了单纯看就业增量的读法', [self.PART_SINCE_JAN]), [])

    def test_direction_word_against_the_fact_still_blocks(self):
        out = layer6_sign_direction('劳动参与率较一月下降幅度 0.5 个百分点说明参与率在上升',
                                    [self.PART_SINCE_JAN])
        self.assertEqual([x['code'] for x in out], ['sign_direction_mismatch'])

    def test_when_the_facts_own_number_is_present_the_whole_clause_counts(self):
        out = layer6_sign_direction('信息业就业月变化 2.3 万人构成了就业增长的主要引擎',
                                    [self.INFO])
        self.assertEqual([x['code'] for x in out], ['sign_direction_mismatch'])


class CompoundDirection(unittest.TestCase):
    """One verb covering a sector that fell and one that rose is wrong whichever the writer meant."""

    INFO = {'id': 'information', 'label': '信息业就业月变化', 'value': -23000, 'unit': 'persons',
            'period': '2026-08', 'source_block_ids': ['b1']}
    HEALTH = {'id': 'health', 'label': '医疗保健就业月增量', 'value': 13000, 'unit': 'persons',
              'period': '2026-08', 'source_block_ids': ['b1']}
    FOOD = {'id': 'food', 'label': '餐饮与酒吧就业月增量', 'value': 59000, 'unit': 'persons',
            'period': '2026-08', 'source_block_ids': ['b1']}
    REVISION = {'id': 'revision_total', 'label': '前两月合计上修', 'value': 55000,
                'unit': 'persons', 'period': '2026-08', 'source_block_ids': ['b1']}
    PART_SINCE_JAN = {'id': 'participation_since_jan', 'label': '劳动参与率较一月下降幅度',
                      'value': 0.5, 'unit': 'percentage_points_decline', 'period': '2026-08',
                      'source_block_ids': ['b1']}

    def test_a_fallen_sector_included_in_an_engine_of_growth(self):
        out = layer6_sign_direction(
            '信息业就业减少 2.3 万人与医疗保健就业增加 1.3 万人共同构成了就业增长的主要引擎',
            [self.INFO, self.HEALTH])
        self.assertIn('compound_direction_over_opposite_facts', [x['code'] for x in out])

    def test_two_sectors_moving_the_same_way_are_fine(self):
        self.assertEqual(layer6_sign_direction(
            '餐饮与酒吧就业增加 5.9 万人和医疗保健就业增加 1.3 万人共同支撑了整体增长',
            [self.FOOD, self.HEALTH]), [])

    def test_each_direction_word_before_its_own_figure_is_fine(self):
        """The renderer writes the direction ahead of the number, so a word between two figures
        belongs to the one that follows it, not to the one before."""
        self.assertEqual(layer6_sign_direction(
            '结合前两个月合计上修 5.5 万人及参与率较一月下降 0.5 个百分点的数据',
            [self.REVISION, self.PART_SINCE_JAN]), [])


class RestatedSentences(unittest.TestCase):
    """A repair pass appended a sentence carrying the same two facts as an existing one. Both
    passed every evidence gate; together they are one paragraph written twice."""

    SLOTS = [{'slot_id': 'S08', 'value_rendered': '5.5 万人', 'direction_word': '上修',
              'rendered': '前两个月合计上修 5.5 万人'},
             {'slot_id': 'S09', 'value_rendered': '0.5 个百分点', 'direction_word': '下降',
              'rendered': '劳动参与率较一月下降 0.5 个百分点'},
             {'slot_id': 'S02', 'value_rendered': '16.2 万人', 'direction_word': '增加',
              'rendered': '8 月非农就业增加 16.2 万人'}]

    def rows(self, texts):
        return [{'sentence_id': f's{i + 1}', 'text': t, 'kind': 'interpretation',
                 'slot_ids': ['S01'], 'model_written_digits': [], 'proposed_thresholds': [],
                 'misframed_values': []} for i, t in enumerate(texts)]

    def test_two_sentences_on_the_same_fact_pair_block(self):
        texts = ['当前劳动参与率处于水平，结合前两个月合计上修 5.5 万人及劳动参与率较一月下降 0.5 个百分点，供给收紧。',
                 '修正项与参与率改变了解读，前两个月合计上修 5.5 万人，而劳动参与率较一月下降 0.5 个百分点，供给可能收紧。']
        out = form_check('\n'.join(texts), self.rows(texts), self.SLOTS)
        self.assertIn('sentence_restates_another', [x['code'] for x in out['findings']])
        self.assertEqual(out['form_status'], 'failed')

    def test_one_shared_fact_is_not_a_restatement(self):
        texts = ['前两个月合计上修 5.5 万人，说明前期数据被低估。',
                 '前两个月合计上修 5.5 万人之外，8 月非农就业增加 16.2 万人同样偏强。']
        out = form_check('\n'.join(texts), self.rows(texts), self.SLOTS)
        self.assertNotIn('sentence_restates_another', [x['code'] for x in out['findings']])


class DeterministicCharts(unittest.TestCase):
    """A chart is a function of the fact pack. If the facts change and the picture does not,
    the picture is decoration."""

    def setUp(self):
        self.packet = json.loads(
            (ROOT / 'evidence_loop/sources/packets/75155f58f5a995e3.json').read_text())
        self.used = {f['id'] for f in self.packet['facts']}

    def test_same_pack_renders_byte_identical(self):
        a = visuals.sector_bars(self.packet, self.used)['svg']
        b = visuals.sector_bars(self.packet, self.used)['svg']
        self.assertEqual(a, b)

    def test_changing_a_fact_changes_the_chart(self):
        before = visuals.sector_bars(self.packet, self.used)['svg']
        mutated = json.loads(json.dumps(self.packet))
        for f in mutated['facts']:
            if f['id'] == 'information':
                f['value'] = -91000
        after = visuals.sector_bars(mutated, self.used)['svg']
        self.assertNotEqual(before, after)
        self.assertIn('9.1 万人', after)
        self.assertNotIn('9.1 万人', before)

    def test_every_drawn_number_carries_its_fact_id(self):
        for builder in (visuals.sector_bars, visuals.level_vs_average):
            got = builder(self.packet, self.used)
            svg = got['svg']
            for fid in got['facts']:
                fx = next(f for f in self.packet['facts'] if f['id'] == fid)
                drawn = render_value(fx)
                # the rendered figure and a data-fact-id for it are both present
                self.assertIn(drawn, svg)
                self.assertIn(f'data-fact-id="{fid}"', svg)

    def test_a_sign_survives_into_the_drawing(self):
        """information is a decline; it must not be drawn as a rising bar."""
        svg = visuals.sector_bars(self.packet, self.used)['svg']
        self.assertIn(f'fill="{visuals.DOWN}" data-fact-id="information"', svg)

    def test_chart_is_chosen_from_the_question_not_the_facts(self):
        draft = {'sentence_to_source_ledger': [{'text': 'x', 'fact_ids': sorted(self.used),
                                                'proposed_thresholds': []}]}
        order_a, w_a, _, _ = visuals.choose('a', draft, self.packet,
                                            '就业行业构成对需求与成本意味着什么')
        order_b, w_b, _, _ = visuals.choose('b', draft, self.packet,
                                            '什么新增证据足以改变交易决策，如何预先定义判断失效')
        # identical fact usage, different questions, different first choice
        self.assertEqual(order_a[0], 'sector_bars')
        self.assertEqual(order_b[0], 'condition_matrix')

    def test_a_question_matching_nothing_gets_no_chart(self):
        draft = {'sentence_to_source_ledger': [{'text': 'x', 'fact_ids': sorted(self.used),
                                                'proposed_thresholds': []}]}
        order, weights, _, _ = visuals.choose('c', draft, self.packet, '今天午饭吃什么')
        self.assertEqual(order, [])


class ChartLabelsCarrySign(unittest.TestCase):
    """A chart has no sentence frame around it, so a label has to read correctly on its own.
    The first version drew 信息业就业月变化 as "2.3 万人" with the fall carried only by colour."""

    NEG = {'id': 'information', 'label': '信息业就业月变化', 'value': -23000, 'unit': 'persons'}
    LABELLED = {'id': 'part_time_decline', 'label': '经济原因兼职人数减少', 'value': 414000,
                'unit': 'persons_decline'}
    POS = {'id': 'payroll', 'label': '非农就业月增量', 'value': 162000, 'unit': 'persons'}

    def test_negative_value_with_a_neutral_label_gets_a_minus(self):
        self.assertEqual(visuals.chart_value(self.NEG), '−2.3 万人')

    def test_label_that_already_says_the_direction_is_not_double_marked(self):
        self.assertEqual(visuals.chart_value(self.LABELLED), '41.4 万人')

    def test_positive_value_is_unchanged(self):
        self.assertEqual(visuals.chart_value(self.POS), '16.2 万人')


class ConditionMatrixNeedsConditions(unittest.TestCase):
    """A table headed 失效条件 whose condition column is entirely "—" is worse than no table."""

    def setUp(self):
        self.packet = json.loads(
            (ROOT / 'evidence_loop/sources/packets/75155f58f5a995e3.json').read_text())
        self.used = {f['id'] for f in self.packet['facts']}

    def test_no_conditions_declines_to_render(self):
        self.assertIsNone(visuals.condition_matrix(self.packet, self.used))

    def test_invalidation_sentence_is_enough(self):
        got = visuals.condition_matrix(self.packet, self.used,
                                       invalidation=['失效条件为若失业率跌破 4.1% 则判断不成立。'])
        self.assertIsNotNone(got)
        self.assertIn('作者写下的失效条件', got['svg'])

    def test_attached_threshold_is_enough(self):
        got = visuals.condition_matrix(self.packet, self.used,
                                       conditions={'unemployment_rate': '4.6%'})
        self.assertIsNotNone(got)
        self.assertIn('4.6%', got['svg'])


class ConsensusWithoutASource(unittest.TestCase):
    """The fact pack states it holds no consensus forecasts, so any comparison against a market
    expectation is unsourced no matter which verb carries it. A reactivation draft slipped through
    with 「与市场预期出现显著背离」 because the rule only listed 高于/低于/好于/差于/超出/不及."""

    FX = [ALLOWED['payroll']]

    def flagged(self, s):
        return 'out_of_evidence_assertion' in codes(layer3_entailment(s, self.FX, PACKET))

    def test_divergence_from_expectations(self):
        self.assertTrue(self.flagged('非农就业数字与市场预期出现显著背离'))

    def test_naming_a_market_expectation_at_all(self):
        self.assertTrue(self.flagged('这一读数已经反映了市场预期'))

    def test_analyst_expectation(self):
        self.assertTrue(self.flagged('该数字明显偏离分析师预期'))

    def test_expectation_gap_term(self):
        self.assertTrue(self.flagged('本次公布存在明显的预期差'))

    def test_english_versus_consensus(self):
        self.assertTrue(self.flagged('162k versus consensus of 145k'))

    def test_english_diverges_from_expectations(self):
        self.assertTrue(self.flagged('The print diverges from expectations'))

    def test_original_forms_still_caught(self):
        self.assertTrue(self.flagged('时薪环比增长高于预期'))
        self.assertTrue(self.flagged('payroll growth beat consensus'))

    def test_expected_return_is_a_different_word(self):
        """预期收益 is not a claim about a market forecast."""
        self.assertFalse(self.flagged('交易者应关注长期的预期收益而非单月读数'))

    def test_a_sentence_with_no_consensus_reference_passes(self):
        self.assertFalse(self.flagged('8 月非农就业增加 16.2 万人'))

    def test_still_passes_when_a_consensus_source_is_supplied(self):
        f = layer3_entailment('非农与市场预期出现背离', self.FX, PACKET,
                              extra_sources={'consensus': {'provider': 'verified estimate feed',
                                                           'value': 145000}})
        self.assertNotIn('out_of_evidence_assertion', codes(f))


class SourceAnnouncedRecord(unittest.TestCase):
    """No typed number establishes a record, so the claim is blocked by default. But when the
    document itself announces one, relaying it with attribution is reporting — and adopting it
    without attribution is still the writer's own claim."""

    SRC = {**PACKET, 'full_narrative': 'Record-Breaking Quarterly Performance Driven by AI Demand'}
    NO_REC = {**PACKET, 'full_narrative': 'Quarterly results were in line with the prior period.'}

    def codes(self, sentence, packet):
        return {x['code'] for x in layer3_entailment(sentence, [], packet)}

    def test_attributed_relay_is_allowed(self):
        c = self.codes('新闻稿称本季创纪录。', self.SRC)
        self.assertIn('record_relayed_from_source', c)
        self.assertNotIn('unsupported_relation', c)

    def test_adopting_the_claim_without_attribution_is_blocked(self):
        c = self.codes('本季创纪录。', self.SRC)
        self.assertIn('unattributed_source_record', c)

    def test_record_claim_with_no_such_source_stays_blocked(self):
        self.assertIn('unsupported_relation', self.codes('本季创纪录。', self.NO_REC))

    def test_english_attribution(self):
        c = self.codes('The company says this was a record quarter.', self.SRC)
        self.assertIn('record_relayed_from_source', c)

    def test_proof_and_priced_in_are_untouched(self):
        self.assertIn('unsupported_relation', self.codes('这已经定价了。', self.SRC))
