from live import draft_qa


def test_zh_dates_are_not_contradicting_metrics():
    assert draft_qa.contradiction_findings('2026年9月PMI重回扩张，单月数据不足以确认趋势。') == []
    assert draft_qa.contradiction_findings('2026年7月亚马逊披露，客户平均每单花费高出40%以上。') == []


def test_real_contradiction_still_flagged():
    out = draft_qa.contradiction_findings('PMI为50.1。PMI为49.0。')
    assert out and out[0]['code'] == 'self_contradiction'
