"""Oct 7 ZH template fixes: pricing-gap endings, 直接 cap, reverse-restatement endings (all soft)."""
from datetime import datetime, timezone
import json

from live import anti_repeat, compose_shapes, hedge, qa_levels, zh_register as zr

# donor_fill_REPORT #2 / #4 closers and other variants named in the brief
GAP_ENDINGS = ['二级市场对这种隐性的杠杆风险显然还没有充分定价。',
               '二级市场对这种财务与 AI 深度绑定的动作，目前的定价还不够充分。',
               '这部分增量没有被充分计价。',
               '这些风险尚未反映在估值里。',
               '最后接盘的是后知后觉的资金。',
               "The market hasn't priced this in yet."]
CONCRETE = ['接下来要盯11月的国债拍卖尾差。', '这次降息落地，资金会先回到长端。',
            'Treasury supply is the thing to watch in November.']


def test_pricing_gap_ending_detected():
    for line in GAP_ENDINGS:
        body = '供给收紧了。' + line
        assert zr.pricing_gap_ending(body), line
        assert zr.template_ending_findings(body)[0]['code'] == 'template_ending'


def test_concrete_ending_not_flagged_and_mid_body_gap_not_an_ending():
    for line in CONCRETE:
        assert not zr.template_ending_findings('判断在前。' + line)
    assert not zr.template_ending_findings('市场还没充分定价。所以接下来要看12月的点阵图。')


def test_template_ending_names_recent_and_same_day_repeat():
    body = '利差会走阔。' + GAP_ENDINGS[0]
    detail = zr.template_ending_findings(body, recent_bodies=['旧稿。' + GAP_ENDINGS[2]],
                                         same_day_bodies=['别的号。' + GAP_ENDINGS[3]])[0]['detail']
    assert '最近' in detail and '今天别的账号' in detail
    # outside the window (persona's previous 4) is not a repeat
    old = ['旧稿。' + GAP_ENDINGS[2]] + ['普通结尾。'] * 4
    assert '最近' not in zr.template_ending_findings(body, recent_bodies=old)[0]['detail']


def test_template_ending_is_soft_with_fix_text():
    assert 'template_ending' in qa_levels.SOFT and 'template_ending' not in qa_levels.HARD
    assert 'concrete consequence' in qa_levels.FIXES['template_ending']


def test_prompts_no_longer_ask_for_what_is_not_priced():
    assert '还没被定价的是什么' not in zr.SYSTEM_ZH and '还没充分定价' in zr.SYSTEM_ZH
    assert not any('还没被定价的是什么' in r for r in zr.RULES_ZH)
    for spec in compose_shapes.SHAPES.values():
        assert 'what is not priced' not in spec.get('en', '') and '还没被定价' not in spec.get('zh', '')


def test_batch_one_pricing_gap_ending_and_zhijie_in_at_most_two():
    rows = [{'account_id': 'zh_macro', 'body': '甲。' + GAP_ENDINGS[0]},
            {'account_id': 'zh_industry', 'body': '乙。' + GAP_ENDINGS[1]},
            {'account_id': 'a', 'body': '这直接导致杠杆被低估。'},
            {'account_id': 'b', 'body': '这直接削弱了需求。'},
            {'account_id': 'c', 'body': '财务治理直接嵌进产品。'}]
    out = zr.batch_template_findings(rows)
    assert set(out) == {1, 4}
    assert out[1][0]['code'] == 'template_ending' and 'zh_macro' in out[1][0]['detail']
    assert out[4][0]['code'] == 'connective_repeat' and '直接' in out[4][0]['detail']
    compose_shapes.batch_findings(rows)
    assert any(f['code'] == 'template_ending' for f in rows[1]['post_checks'])
    assert not any(f['code'] == 'template_ending' for f in rows[0].get('post_checks') or [])


def test_zhijie_once_per_draft_not_cross_window_and_finance_terms_excluded():
    body = '这直接导致杠杆被低估。供给直接削弱了需求。'
    assert '直接' in zr.connective_repeat_findings(body)[0]['detail']
    assert not zr.connective_repeat_findings('这直接导致杠杆被低估。', ['直接削弱了需求。'])
    assert '直接' not in zr.recent_connectives(['直接削弱了需求。'])
    assert zr.zhijie_count('直接融资占比下降，直接投资回落。') == 0
    assert not zr.connective_repeat_findings('直接融资降了。这直接导致利差走阔。')


def test_reverse_restatement_ending_is_hedge_only():
    # donor_fill #5 closer
    body = ('10月1日公布的最新情况印证了这一点。只要交易商的资产负债表空间还在，接下来遇到国债供给放量时价格就能稳住；'
            '反过来说，现在的平稳完全依赖于这部分释放出来的敞口。')
    kinds = [k for _, k in hedge.hedge_sentences(body)]
    assert kinds == ['reverse_restate']
    assert hedge.hedge_findings(body)[0]['code'] == 'hedge_only'
    assert [k for _, k in hedge.hedge_sentences('价差收窄了。换句话说，交易商又回来了。')] == ['reverse_restate']
    assert hedge.hedge_sentences('Spreads tightened. Put differently, dealers are back.')


def test_reverse_restatement_kept_with_new_number_or_mid_body():
    assert not hedge.hedge_sentences('价差收窄了。换句话说，10年期拍卖尾差降到0.3个基点。')
    assert not hedge.hedge_sentences('价差收窄了。换句话说，周期能走多久取决于厂商愿意让供给紧到什么程度。')
    mid = '价差收窄了。换句话说，交易商回来了。拍卖更顺。接下来盯11月供给。'
    assert not [k for _, k in hedge.hedge_sentences(mid) if k == 'reverse_restate']


def test_defensive_conditionals_with_lead_word():
    assert [k for _, k in hedge.hedge_sentences('会继续加息。但如果核心通胀掉头，那就说明加息周期并没有结束。')] == ['falsifier_restate']
    assert [k for _, k in hedge.hedge_sentences('会继续加息。不过除非就业突然转强，否则这个判断依然成立。')] == ['falsifier_restate']
    assert hedge.hedge_sentences('会继续加息。除非通胀回落到2%以下，否则这个判断依然成立。') == []   # new number stays
    assert '反过来说' in hedge.RULE_ZH


def test_load_same_day_reads_other_personas_only(tmp_path, monkeypatch):
    monkeypatch.setattr(anti_repeat, 'HISTORY_DIR', tmp_path)
    monkeypatch.setattr(anti_repeat, 'FALLBACK_DIR', tmp_path / 'none')
    rows = {'zh_macro': [{'ts': '2026-10-07T08:00:00+00:00', 'text': 'today macro'},
                         {'ts': '2026-10-06T08:00:00+00:00', 'text': 'yesterday'}],
            'zh_industry': [{'ts': '2026-10-07T09:00:00+00:00', 'text': 'today industry'}]}
    for k, v in rows.items():
        (tmp_path / f'{k}.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in v))
    now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    assert anti_repeat.load_same_day('zh_industry', now) == ['today macro']
    assert sorted(anti_repeat.load_same_day(None, '2026-10-07T12:00:00Z')) == ['today industry', 'today macro']
