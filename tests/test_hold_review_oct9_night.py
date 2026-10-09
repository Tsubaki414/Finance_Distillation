"""Oct 9 night HOLD review (Fiona: HOLD only for fabrication, distorted source, wrong numbers, unreadable jargon,
duplicates). The 10-09 over-strict holds: a company / venue name read as jargon (#19 SK Group, #33 QFEX perp venue), a
kept condition not recognised (#15 'losing the $107,000 level'), a $TICKER meme draft held off_lane (#27), an added
interpretive line in an unattributed evergreen (#3, #9) and a fixable ZH boilerplate phrase (#9 核心逻辑)."""
from live import archive_evergreen as ae, archive_lookback as al, editorial_style as es, engagement as E, lane_fit
from live.draft_qa import readability_findings


def test_names_followed_by_what_they_are_are_not_jargon():
    assert readability_findings('SK Group: the capacity expansion is gated by power.') == []
    assert readability_findings('The QFEX perp venue already has $140.7m in open interest.') == []
    assert readability_findings('ABC 交易所 上线了新币') == []
    assert readability_findings('The PFOF ban hits retail flow')[0]['detail'] == 'PFOF'   # real jargon still HARD


def test_condition_kept_by_until_or_by_its_level():
    card = {'claim': {'claim_type': 'conditional', 'condition': 'we meaningfully lose 107k'}}
    kept = 'He said meaningfully losing the $107,000 level would expose lower demand.'
    assert al.claim_findings(kept, card) == []
    assert al.claim_findings('Leaning bullish until a weekly structure shift.', card) == []
    assert al.claim_findings('He was bullish. BTC is now 82k.', card)[0]['code'] == 'archive_condition_dropped'


def test_meme_ticker_with_market_cap_is_on_lane():
    acct = {'id': 'crypto_meme_zh', 'retrieval_beats': ['crypto_meme']}
    body = '$CRH 的走势背后，筹码换手透着一股荒谬感。\n顶着 Robinhood 的牌子，市值竟然才刚刚突破 100 万美元。'
    assert lane_fit.draft_check(acct, body)['ok']
    assert not lane_fit.draft_check(acct, 'Robinhood 股价今天涨了 5%，美股情绪回暖。')['ok']


def test_evergreen_added_view_is_soft_but_added_fact_is_hard():
    soft = ae.judge_findings(lambda m: {'faithful': False, 'issues': [
        {'type': 'added_claim', 'detail': '“早期的注意力确实需要依靠故事来获取。”'}]}, 'x', {'date': 'd', 'text': 't', 'verdict': {}})
    assert [f['code'] for f in soft] == ['evergreen_added_view'] and soft[0]['level'] == 'soft'
    hard = ae.judge_findings(lambda m: {'faithful': False, 'issues': [
        {'type': 'added_claim', 'detail': 'adds that revenue grew 40%'},
        {'type': 'distorted_idea', 'detail': 'reverses the point'}]}, 'x', {'date': 'd', 'text': 't', 'verdict': {}})
    assert [f['code'] for f in hard] == ['evergreen_misrepresents'] and hard[0]['level'] == 'hard'


def test_boilerplate_only_hard_is_autofixed():
    body = '个股层面的利空传闻，未必能扭转整个板块的核心逻辑。'
    found = [{'code': 'editorial_cliche', 'level': 'hard', 'detail': '核心逻辑'}]
    assert es.autofix_if_only_cliche(body, 'zh', found) == '个股层面的利空传闻，未必能扭转整个板块的逻辑。'
    assert es.autofix_if_only_cliche('不是涨而是跌', 'zh', [{'code': 'editorial_cliche', 'level': 'hard'}]) is None
    both = found + [{'code': 'evergreen_misrepresents', 'level': 'hard'}]
    assert es.autofix_if_only_cliche(body, 'zh', both) is None


def test_engagement_off_target_is_soft_rewrite_trigger():
    t = 'i expect culture and collective belief to become increasingly valuable as AI content floods everything'
    f = E.findings("I'm wary of quantum narratives when Grayscale's Zcash ETF took $1 billion.", 'reply', 'en', t)
    assert 'engage_off_target' in {x['code'] for x in f} and 'engage_off_target' in E.REPAIR_TRIGGER
    assert 'engage_off_target' not in E.HARD_CODES
    ok = E.findings('Culture as a moat, sure, but belief gets priced fast: 3 of 5 AI coins fell 40%.', 'reply', 'en', t)
    assert 'engage_off_target' not in {x['code'] for x in ok}
    assert E.findings('ETH 2400 这一下更像扫流动性。', 'reply', 'zh', '$ETH tapped the $2,400 level before bounceback.') == []
