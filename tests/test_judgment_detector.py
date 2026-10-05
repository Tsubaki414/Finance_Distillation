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


def test_en_macro_thesis_opening_matches_stance_field_not_keywords():
    """Judgment-first EN thesis can paraphrase the stance; do not false-flag on low lexical overlap."""
    stance = {
        'account_view': ('Goldman pushing the second hike to December while flagging a real chance '
                         'the FOMC stops altogether is a meaningful dovish shift, but one data-dependent '
                         'caveat does not make it a forecast — the Fed needs a run of softening prints '
                         'before that door closes.'),
        'view': {
            'subject': 'Fed funds rate path / number of additional rate hikes',
            'direction': 'lower',
            'reasoning': [
                "Goldman's pushback of the second hike to December signals a dovish lean.",
                "The strong chance framing for an FOMC pause is plausible but premature.",
            ],
        },
    }
    body = ("Lots of dovish talk about a Fed pause, but it's mostly recency bias.\n\n"
            "Economists pushed the second hike to December.")
    assert not flagged(body, stance)
    # Still flag pure data / question against the same stance
    assert flagged('August core PCE printed 0.25% mom.\n\nEconomists pushed the hike back.', stance)
    assert flagged('Is the Fed done hiking?\n\nOdds fell this week.', stance)


def test_leading_figure_with_evaluative_verb_is_not_data_led():
    stance = {'account_view': 'Resilience narratives are overdone while 5% yields keep financial conditions tight.',
              'view': {'subject': 'US Treasury yields / market resilience', 'direction': 'bearish',
                       'reasoning': ['5% yields challenge the resilience narrative.']}}
    assert not flagged('5% US Treasury yields challenge the narrative of ongoing market resilience.\n\nBuyers hesitate.', stance)
    assert flagged('5% was the print on the 10-year.\n\nVolume was light.', stance)


def test_rhetorical_question_with_stance_overlap_passes():
    stance = {'account_view': 'Broadcom headline numbers obscure the real margin risk.',
              'view': {'subject': 'Broadcom earnings margins', 'direction': 'bearish',
                       'reasoning': ['Look past the headline numbers on Broadcom.']}}
    assert not flagged('Is anyone actually looking past the headline numbers on Broadcom?\n\nMargins tell a thinner story.', stance)


def test_en_thesis_without_stance_not_false_positive():
    """Offline/QA scans often lack stance; declarative thesis openings must not FP."""
    assert not flagged("Goldman pushing their second hike to December is a dovish shift, but premature.\n\nPCE cooled.", None)
    assert not flagged("Don't front-run the bond market contagion.\n\nTLT skew rank 100.", None)
    assert not flagged("The claim that market resilience persists doesn't seem to check out.\n\nYields broke 5%.", None)
    assert not flagged("Rate expectations are losing their grip on Bitcoin.\n\nOdds fell 66% to 22%.", None)
    # Still flag bare data / bare question without stance
    assert flagged("October hike odds fell from 66% to 22%.\n\nBitcoin rose 1%.", None)
    assert flagged("Why is Bitcoin ignoring the Fed?\n\nOdds fell.", None)
