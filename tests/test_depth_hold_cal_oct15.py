"""Oct 15 FD_DEPTH_HOLD_CAL: take posts with a grounded figure + an own judgment line no longer hard:depth.
Fixtures are synthetic, shaped after 10-15's held rows (no live donor / tweet / article text)."""
import pathlib

import pytest

from live import depth_check as dc

ON, OFF = {}, {'FD_DEPTH_HOLD_CAL': '0'}

# (body, lang, post_type, source_text, units) - each held by HEAD (Oct 13 rules), passes with the calibration
PASS = [
    # EN data_take, quote: share-of-volume figure + negated judgment, no MARKERS / INSIGHT token
    ('ChainDesk reports that 58% of tokenized stock volume on the chain trades outside New York hours.\n\n'
     'Time zones are not holding back these listings, with $3.1B traded last month',
     'en', 'data_take', 'Did you know 58% of tokenized stock volume trades outside New York hours?', None),
    # ZH data_take: drawdown + vol-index move + a so-what line
    ('某芯片龙头从近期高点回撤了9%，恐慌指数盘中涨了6%。短线情绪在波动，资金的避险动作并没有改变中期方向',
     'zh', 'data_take', '恐慌指数 +6%', None),
    # EN reply judgment: a support level from the source + an own forecast
    ('ChartGuy notes that SOL is sitting on its $142 support zone. I think it eventually gives way and we '
     'retest $128 first.', 'en', 'judgment_take', '$SOL is now at its $142 support zone.', None),
    # EN quote judgment: level + "leaves the door open" implication
    ('ChartGuy notes that SOL is sitting on its $142 support zone.\n\n'
     'Losing it leaves the door open to $128 before anyone gets a real bounce.',
     'en', 'judgment_take', '$SOL is now at its $142 support zone.', None),
    # EN data_take: allocation figure + evaluative line
    ('another token launch with most of the supply labelled community\n\n40% community looks nice on paper\n\n'
     '25% insiders and 25% team', 'en', 'data_take', 'XYZ protocol publishes tokenomics, 40% to community', None),
    # ZH data_take: injected amount + "还得看" so-what
    ('这个平台三个月砸了 0.8 亿美元做激励。钱是撒出去了，能不能留住用户还得看后面行情接不接得住',
     'zh', 'data_take', '某平台：激励计划约三个月投入 0.8 亿美元', None),
    # figure only in the units (title-only source): units carry it
    ('链上数据显示相关地址在推荐前已经建仓。\n\n估算这批地址赚了约 3 万美元，这种老鼠仓玩法把散户当傻子。',
     'zh', 'data_take', '某分析机构指控关联钱包在推荐前交易',
     [{'statement': '关联钱包获利约 3 万美元', 'source_spans': [{'exact_text': 'profit of about $30k'}],
       'numbers': [{'text': '3 万美元'}]}]),
]

# must still HOLD with the calibration on
HOLD = [
    # pure headline relay, one sentence
    ('ABC protocol announced its token supply split: 40% community.', 'en', 'data_take',
     'ABC protocol publishes tokenomics, 40% to community', None),
    # facts only, two sentences, no judgment line
    ('Treasury firm bought 2,100 BTC last week. It now holds 31,500 coins.', 'en', 'data_take',
     'Treasury firm adds 2,100 BTC, holdings rise to 31,500', None),
    ('某协议公布代币经济学，40% 分配给社区。\n\n团队和投资人各拿两成，基金会拿剩下的部分。', 'zh', 'data_take',
     '某协议公布代币经济学，40% 分配给社区', None),
    # reported speech: the official's claim relayed, not the post's own judgment
    ('Fed official speaks on inflation. The governor says rates won\'t fall soon with inflation near 3%.',
     'en', 'judgment_take', 'Governor: rates to stay high, inflation near 3%', None),
    ('联储官员谈通胀。理事表示短期不会降息，通胀仍高于2%。', 'zh', 'judgment_take', '联储理事：通胀高于2%', None),
    # judgment line but no figure the source / units carry (invented or absent)
    ('Memory makers look stretched here. I think the cycle is not over yet.', 'en', 'judgment_take',
     'Memory fundamentals are still strong', None),
    ('Supply rose to 9,999 coins. I think this is not over.', 'en', 'data_take', 'Supply rose sharply', None),
    # judgment sentence is the source's own sentence restated (headline copy)
    ('Gold drops 2%. Gold drop is not the end for bulls, analysts see support.', 'en', 'judgment_take',
     'Gold drops 2%: Gold drop is not the end for bulls, analysts see support', None),
    # reaction only (no judgment / so-what)
    ('某联储官员评论9月通胀高于预期。\n通胀数据竟然比预期高，确实没想到', 'zh', 'judgment_take',
     '某联储官员称9月通胀高于预期', None),
    # dates / list markers are not figures
    ('1. On October 14, 2026 the index fell.\n2. I think this is not the bottom.', 'en', 'judgment_take',
     'Index falls on October 14, 2026', None),
    # single sentence take: still held (needs a figure line + a take line)
    ('Rate hike odds at 17% look like the market is not pricing risk.', 'en', 'data_take',
     'Hike odds fall to 17%', None),
]


def _f(case, env, **kw):
    body, lang, pt, src, units = case
    return dc.findings(body, lang, None, env=env, source_text=src, post_type=pt, units=units, **kw)


@pytest.mark.parametrize('case', PASS)
def test_grounded_take_passes(case):
    assert _f(case, ON) == []


@pytest.mark.parametrize('case', PASS)
def test_head_would_hold_pass_cases(case):
    assert _f(case, OFF)[0]['code'] == 'depth'


@pytest.mark.parametrize('case', HOLD)
def test_relay_still_held(case):
    assert _f(case, OFF)   # HEAD holds these too
    f = _f(case, ON)
    assert f and f[0]['code'] == 'depth' and f[0]['level'] == 'hard'


@pytest.mark.parametrize('case', PASS + HOLD)
def test_switch_off_is_head(case):
    body, lang, pt, src, units = case
    # HEAD's signature had no post_type / units: with the switch off they change nothing
    assert _f(case, OFF) == dc.findings(body, lang, None, env=OFF, source_text=src)


def test_only_take_kinds():
    body, lang, _, src, units = PASS[2]
    assert dc.findings(body, lang, None, env=ON, source_text=src, post_type='mechanism_explainer')
    assert dc.findings(body, lang, None, env=ON, source_text=src) == dc.findings(body, lang, None, env=OFF,
                                                                               source_text=src)
    assert dc.findings(body, lang, 'reaction', env=ON, source_text=src, post_type=None) == []


def test_needs_grounding_text():
    body, lang, pt, _, _ = PASS[2]
    assert dc.findings(body, lang, None, env=ON, source_text=None, post_type=pt)
    assert dc.grounded_take(body, lang, None) is None


def test_master_switch_and_archive_untouched():
    body, lang, pt, src, _ = HOLD[0]
    assert dc.findings(body, lang, None, env={'FD_DEPTH_CHECK': '0'}, source_text=src, post_type=pt) == []
    assert dc.findings('回看｜2025年10月。BTC 跌了', 'zh', env=ON, post_type='data_take') == []


def test_units_text_shapes():
    assert dc.units_text(None) is None
    assert dc.units_text([{'statement': 'a', 'source_spans': [{'exact_text': 'b'}, 'c'],
                           'numbers': [{'text': '1%'}]}, 'junk']) == 'a b c 1%'


def test_zh_reported_speech_does_not_eat_own_words():
    # 说白了 / 数据 are not reported speech
    assert dc.grounded_take('最新数据里池子收益率 5.2%。看了数据，感觉收益率水分比想象大', 'zh', '池子收益率 5.2%')
    assert dc.grounded_take('币价跌了 8%。说白了这波是杠杆出清，不等于趋势反转', 'zh', '币价跌 8%')


def test_daily_compose_passes_post_type_and_units():
    src = (pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'daily_compose.py').read_text()
    assert "post_type=r.get('post_type'), units=r.get('units'))" in src
