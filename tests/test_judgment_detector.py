"""The 'no clear judgment' check reads the stance: the opening must carry the stance's call
(content overlap) or a clear judgment marker; a question / bare data opening is not a judgment."""
from live import compose

EN_STANCE = {'account_view': 'Rate expectations are not the main driver of Bitcoin right now.'}
ZH_STANCE = {'account_view': '比特币对降息预期反应钝化，驱动力转向链上资金流和监管信号。'}


def flagged(body, stance):
    return 'no_judgment' in [f['code'] for f in compose.judgment_findings(body, stance)]


def test_opening_carrying_the_stance_passes():
    assert not flagged("Rate expectations aren't driving Bitcoin right now.\n\nOdds fell 66% to 22%.", EN_STANCE)
    assert not flagged('比特币对降息预期的钝感说明单靠货币政策已经带不动盘面了。\n\n整整一周加息概率从66%掉到22%。', ZH_STANCE)


def test_data_or_question_opening_flagged():
    assert flagged('October hike odds fell from 66% to 22% this week.\n\nBitcoin rose 1%.', EN_STANCE)
    assert flagged('Why is Bitcoin ignoring the Fed?\n\nRate expectations are not the driver.', EN_STANCE)
    assert flagged('10月加息概率从66%掉到22%。比特币只涨了1%。', ZH_STANCE)


def test_without_stance_judgment_marker_still_counts():
    assert not flagged('Memory pricing looks fragile from here. Revenue rose 4.8x.', None)
    assert flagged('Revenue rose 4.8x to $54.23 billion.', None)
