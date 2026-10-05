"""ZH no_judgment calibration (2026-10-05).

Offline replay of 177 real drafts showed 12/57 ZH openings falsely flagged as
`no_judgment` even though each one leads with the account's call. Those false flags
trigger an unnecessary judgment rewrite. Fixtures below are real draft openings paired
with their real stances. Bare data / bare questions must still be flagged.
"""
import pytest

from live import compose

ZH_MACRO_RESILIENCE = {
    'account_view': '海外加息预期升温确实形成压制，但韧性能否持续还要看流动性方向有没有实质转变，现阶段偏多但需设条件。',
    'view': {'subject': 'market resilience', 'direction': 'bullish'}}
ZH_MACRO_PMI = {
    'account_view': 'PMI刚刚回到荣枯线上方，生产端加速明显，但新订单环比小幅回落，单月数据不足以确认趋势，需观察后续流动性配合。',
    'view': {'subject': '中国制造业产出', 'direction': 'bullish'}}
ZH_IND_AI = {
    'account_view': '需求超过供给这个方向没问题，但定价权能否撑过新一轮产能扩张才是关键，光看周期长度不够。',
    'view': {'subject': 'AI基础设施需求周期', 'direction': 'bullish'}}
ZH_IND_ALEXA = {
    'account_view': 'Alexa购物的客单价和Prime转化数据看起来不错，但定价能力能否在产能扩张后持续才是关键问题。',
    'view': {'subject': 'Alexa for Shopping货币化潜力与Prime会员增长', 'direction': 'bullish'}}
ZH_CRYPTO = {
    'account_view': '比特币短期内对降息预期的钝感反应，恰恰说明当前价格驱动力不在货币政策预期，而在链上资金流与监管信号。',
    'view': {'subject': 'Bitcoin price reaction to declining Fed hike odds', 'direction': 'mixed'}}
EN_MACRO = {
    'account_view': ("Rate hike expectations are tightening financial conditions at the margin, and calling that "
                     "'resilience' requires more than one data point to hold up."),
    'view': {'subject': 'market resilience under rising overseas rate hike expectations', 'direction': 'neutral'}}

REAL_JUDGMENT_OPENINGS = [
    ('韧性犹存，但条件不能省。\n\n加息预期升温。', ZH_MACRO_RESILIENCE),
    ('现阶段市场韧性犹存，但多头逻辑必须加上条件。\n\n流动性还没转向。', ZH_MACRO_RESILIENCE),
    ('生产端加速，需求端在退潮，这份PMI读起来很割裂。\n\n新订单回落。', ZH_MACRO_PMI),
    ('制造业刚回扩张区，别急着线性外推。\n\nPMI回到荣枯线上方。', ZH_MACRO_PMI),
    ('生产加速，但这还撑不起一个趋势判断。\n\n新订单回落。', ZH_MACRO_PMI),
    ('需求超供方向站得住，但定价权另说。\n\n扩产在路上。', ZH_IND_AI),
    ('AI基建周期拉长，定价权必须撑过新一轮扩产。\n\n供给在追。', ZH_IND_AI),
    ('需求超供这个方向没有异议。\n\n关键在定价权。', ZH_IND_AI),
    ('规模化前，这两组数字只能算早期信号。\n\n客单价不错。', ZH_IND_ALEXA),
    ('定价权还没经过规模考验。\n\n转化数据不错。', ZH_IND_ALEXA),
    ('当前比特币的定价逻辑已脱离货币政策预期。\n\n加息概率大跌。', ZH_CRYPTO),
    ('比特币对降息预期已经免疫了。\n\n加息概率大跌。', ZH_CRYPTO),
]


def no_judgment(body, stance):
    return 'no_judgment' in [f['code'] for f in compose.judgment_findings(body, stance)]


@pytest.mark.parametrize('body,stance', REAL_JUDGMENT_OPENINGS)
def test_real_zh_judgment_openings_pass(body, stance):
    assert not no_judgment(body, stance), body.split('\n')[0]


def test_en_evaluative_figure_opening_passes():
    body = '5% US Treasury yields tighten financial conditions at the margin.\n\nOne print is not a trend.'
    assert not no_judgment(body, EN_MACRO)


@pytest.mark.parametrize('body,stance', [
    ('10月加息概率从66%掉到22%。比特币只涨了1%。', ZH_CRYPTO),
    ('PMI为50.1%，新订单指数49.8%。\n\n生产指数51.2%。', ZH_MACRO_PMI),
    ('比特币为什么不涨？\n\n加息概率跌了。', ZH_CRYPTO),
    ('制造业PMI升至50.1%。\n\n前值49.7%。', ZH_MACRO_PMI),
    ('5% was the print on the 10-year.\n\nVolume was light.', EN_MACRO),
])
def test_bare_data_and_bare_questions_still_flagged(body, stance):
    # The compose judgment retry fires on either code; data-heavy openings may surface as data_list.
    codes = {f['code'] for f in compose.judgment_findings(body, stance)}
    assert codes & {'no_judgment', 'data_list'}, body.split('\n')[0]


def test_unrelated_zh_recap_without_judgment_still_flagged():
    # Topic recap with no evaluative move and no stance overlap.
    assert no_judgment('今天发布了一份报告。\n\n报告共二十页。', ZH_MACRO_PMI)


def test_zh_contrast_on_a_data_line_still_flagged():
    assert no_judgment('PMI为50.1%，但新订单指数49.8%。\n\n生产指数51.2%。', ZH_MACRO_PMI)
