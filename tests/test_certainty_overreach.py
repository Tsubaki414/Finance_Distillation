"""Draft certainty must not exceed the stance/units: absolute wording or added forecasts that
no input carries are a SOFT 'certainty_overreach' finding (never a stall)."""
from live import compose, qa_levels

UNITS = [{'statement': 'Reactions to falling hike odds were small or short-lived.',
          'source_spans': [{'exact_text': 'Reactions to drops in hike odds were small or short-lived.'}]},
         {'statement': 'Bitcoin gained about 1% over the week.', 'source_spans': [{'exact_text': 'Bitcoin gained about 1%.'}]}]
STANCE = {'decision': 'adapt', 'account_view': 'Rate expectations are not the main driver of Bitcoin right now.'}
ZH_UNITS = [{'statement': '每次讲话后比特币反应都很微弱且短暂。', 'source_spans': [{'exact_text': 'small or short-lived'}]}]
ZH_STANCE = {'account_view': '比特币对降息预期反应钝化，驱动力转向链上资金流和监管信号。'}


def codes(body, units=UNITS, stance=STANCE, lang='en'):
    return [f['code'] for f in compose.certainty_findings(body, units, stance, lang)]


def test_absolute_upgrade_flagged():
    assert 'certainty_overreach' in codes('Rate expectations are not driving Bitcoin. Any reaction is entirely short-lived.')


def test_supported_wording_clean():
    assert codes('Rate expectations are not driving Bitcoin. Reactions were small or short-lived; it gained about 1%.') == []


def test_added_forecast_flagged_en_and_zh():
    assert 'certainty_overreach' in codes('Rates are not the driver. Bitcoin will stall until flows return.')
    assert 'certainty_overreach' in codes('比特币对降息预期反应钝化。在链上资金流明确前，短期很难有向上的大行情。',
                                          ZH_UNITS, ZH_STANCE, 'zh')


def test_marker_present_in_inputs_is_allowed():
    stance = {'account_view': 'Bitcoin will stay range-bound until ETF flows return.'}
    assert codes('Bitcoin will stay range-bound until ETF flows return.', UNITS, stance) == []
    assert codes('比特币反应都很微弱且短暂。', ZH_UNITS, ZH_STANCE, 'zh') == []


def test_level_is_soft():
    assert qa_levels.level({'code': 'certainty_overreach'}, frame_found=True) == 'soft'
