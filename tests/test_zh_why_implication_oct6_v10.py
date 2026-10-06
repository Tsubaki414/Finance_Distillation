"""Oct 6 v10: ZH drafts read like a riddler (Fiona, v9 pack ZH 0/4). Soft missing_why /
missing_implication / zh_awkward_time checks join the one structure regen."""
import pytest

from live import compose, compose_shapes as cs, qa_levels, zh_register as zr
from tests.test_zh_register_oct6_v5 import SeqFake, STANCE, _iso

# The four ZH drafts Fiona rejected (/workspace/x/human_rates/oct6_v9_rate_pack.md #1-#4).
REJECTED = {
    1: ('此次加息后美联储其实一点都不急着继续动手，接下来纯粹是走过场看数据\n'
        '纽约联储主席Williams直接放话毫无紧迫性，哪怕核心PCE还在3.0%的高位挂着\n'
        '官方对通胀指标的无视，说明市场短期内继续收紧的预期已经打没了。'),
    2: ('AI大厂藏在表外的租赁负债，会让信用利差长期背着额外风险溢价。\n'
        '截至二季度财报季，超大规模科技公司有1.0万亿美元的未生效租约没进资产负债表。\n'
        '这笔庞大的隐性账，意味着市场会一直要求更高的利差来补偿流动性风险。'),
    3: ('美联储这轮紧缩周期会在十二月落地第二次加息，随后就会直接停手。十月份提前动手的风险已经被疲软的就业市场'
        '彻底打下去了。面对这种局面确实需要保持警惕，不要对短期政策路径抱有太多幻想。\n\n'
        '九月份的非农就业仅仅增加了2.9万人。私营部门的新增数据也只有4.6万人。这两个数字放在一起看非常惨淡，'
        '完全不及预期。而且失业率其实已经悄悄爬到了4.18%。劳动力市场的寒气已经完全藏不住了，整体表现相当疲软。\n\n'
        '这种冷清的数据表现直接打乱了原本的加息节奏。短期内连续收紧的压力其实已经大幅减轻了。政策步伐只能被迫'
        '切回到渐进模式，美联储需要时间慢慢消化这些负面反馈。十二月的加息行动就是这轮周期的最后一次。'),
    4: ('Zendesk这次换CFO只是常规的财务招聘？人家这是直接把财务治理死死绑在了AI产品战略上。\n'
        '既然吞下了Forethought这个AI平台，现在正需要懂工程又懂并购的管家来盯紧钱袋子。'
        '面对资源更强的CRM对手，这套班子就是为了死磕投资纪律准备的。'),
}

GOOD = [
    '美联储12月之后大概率先停一停。\n因为9月非农只加了2.9万人，就业撑不住再加息。\n'
    '对债市来说，短端的压力会小一些，接下来要看11月的通胀数据。',
    # v11: 说白了 is banned (avoid_patterns) and no longer counts as an implication
    '存储涨价这波还没走完。\n背后是几家大厂都在压产能，库存其实已经见底。\n所以下游想等降价再补货，估计等不到。',
    'Meta这笔表外租约，信用市场迟早要算进去。\n原因是1.0万亿美元的未生效租约没进资产负债表。\n'
    '换句话说，AI大厂发债的利差会被一直往上推。',
    '油价这轮反弹撑不久。\n主要是需求端没跟上，炼厂开工率还在往下走。\n所以下次会议前，产油国减产的口风才是要盯的。',
]


def _codes(body):
    return {f['code'] for f in zr.why_implication_findings(body, 'zh') + zr.awkward_time_findings(body, 'zh')}


@pytest.mark.parametrize('n', sorted(REJECTED))
def test_rejected_examples_flag(n):
    assert _codes(REJECTED[n]) & {'missing_why', 'missing_implication'}


def test_rejected_specifics():
    assert {'missing_why', 'missing_implication', 'zh_awkward_time'} <= _codes(REJECTED[1])
    assert 'missing_why' in _codes(REJECTED[2])          # 意味着 counts as implication, no reason given
    assert {'missing_why', 'missing_implication', 'zh_awkward_time'} <= _codes(REJECTED[3])
    det = zr.awkward_time_findings(REJECTED[3])[0]['detail']
    assert '随后就会直接' in det and '直接停手' in det     # overlapping phrases both reported


@pytest.mark.parametrize('body', GOOD)
def test_good_examples_pass(body):
    assert _codes(body) == set()
    assert zr.register_findings(body) == []               # the colloquial implication does not trip 研报腔


def test_number_or_shuoming_alone_is_not_a_why():
    body = '美联储12月之后会先停。\n9月非农只加了2.9万人，说明就业很弱。\n对债市来说，短端压力小了。'
    assert {f['code'] for f in zr.why_implication_findings(body)} == {'missing_why'}


def test_en_and_empty_return_nothing():
    en = 'The Fed is done after December. Payrolls rose only 29k.'
    assert zr.why_implication_findings(en, 'en') == [] and zr.awkward_time_findings('走过场', 'en') == []
    assert zr.why_implication_findings('', 'zh') == [] and zr.awkward_time_findings('', 'zh') == []


def test_codes_soft_with_fixes():
    for code in ('missing_why', 'missing_implication', 'zh_awkward_time'):
        assert qa_levels.level({'code': code}, frame_found=False) == 'soft'
        assert code in qa_levels.FIXES
    assert '意味着' in qa_levels.FIXES['missing_implication'] and 'not' in qa_levels.FIXES['missing_implication']


def test_prompt_rules_and_short_shapes_carry_why_and_implication():
    assert any('一句为什么' in r and '一句影响' in r for r in zr.RULES_ZH)   # zh_native: no 「这意味着什么」 wording
    assert '不当谜语人' in zr.SYSTEM_ZH and '随后就会直接停手' in zr.SYSTEM_ZH
    for sid in ('take_short', 'one_number_punch', 'contrarian_question'):
        zh = cs.SHAPES[sid]['zh']
        assert '为什么' in zh and '影响' in zh
        # v11: plain 意味着 allowed; no literal lead-ins as templates (背后是 / 说白了 / 对…来说)
        assert not any(w in zh for w in ('背后是', '说白了', '对…来说', '接下来要看'))


# ---------- compose integration: same single structure regen ----------

RIDDLE_BODY = '存储这轮紧缺还没完。\n厂商就是不想扩产，价格还在涨。\n下游采购节奏随后就会直接停手。'
FIXED_BODY = '存储这轮紧缺还没完。\n因为厂商就是不想扩产，价格其实还在涨。\n对下游来说，之后采购节奏得跟着改。'


def test_compose_structure_regen_carries_new_codes_and_keeps_fix(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    from tests.test_compose import SOURCE
    fake = SeqFake([RIDDLE_BODY, FIXED_BODY])
    result = compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take',
                                    stance_output=dict(STANCE), emotion_contract=False)
    sr = result['structure_retry']
    first = {f['code'] for f in sr['first_findings']}
    assert {'missing_why', 'missing_implication', 'zh_awkward_time'} <= first
    assert '[structure_repair]' in sr['rewrite_note'] and '一句说清' in sr['rewrite_note']   # v11 FIXES wording
    assert fake.payloads[1].get('rewrite_note') == sr['rewrite_note']
    assert sr['kept'] == 'retry'
    assert not {'missing_why', 'missing_implication', 'zh_awkward_time'} & {f['code'] for f in sr['retry_findings']}
    compose_calls = [p for p in fake.payloads if p.get('rewrite_note', '').startswith('[structure_repair]')]
    assert len(compose_calls) == 1                         # one regen, no extra pass


def test_en_compose_skips_zh_checks(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    from tests.test_compose import SOURCE
    fake = SeqFake(['Memory tightness is not over.\nMakers will not add capacity.\nBuyers adjust.'])
    result = compose.compose_source(SOURCE, 'en_industry', fake, post_type='data_take',
                                    stance_output=dict(STANCE, account_view='Memory tightness persists'),
                                    emotion_contract=False)
    found = {f['code'] for f in ((result.get('structure_retry') or {}).get('first_findings') or [])}
    assert not found & {'missing_why', 'missing_implication', 'zh_awkward_time'}
