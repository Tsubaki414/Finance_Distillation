"""fix26 (Oct 7): Sirius editorial-style HARD blocks, beat gate, fill mode, inbox audit and ops page helpers."""
import json
import sys
from datetime import date
from pathlib import Path

from live import compose_inbox, editorial_style as es, qa_levels

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts')]
ACCOUNTS = {a['id']: a for a in json.loads((ROOT / 'live' / 'fd20_accounts.json').read_text())['accounts']}


def codes(body, lang):
    return {f['code'] for f in es.findings(body, lang)}


def test_fiona_oct7_zh_drafts_are_blocked():
    # 墨川 7e3857: the reviewed draft trips the opener, cliché and overclaim blocks
    body = ('难道这波反弹真的撞到天花板了？很显然，比特币的上涨势头正被美债利率死死压制。\n\n'
            '高风险偏好赛道的上涨逻辑在短期内已基本被锁死')
    assert codes(body, 'zh') >= {'rhetorical_opener', 'editorial_cliche', 'overclaim'}
    # Arlo 46b487
    assert 'editorial_cliche' in codes('我觉得症结在于中介成本过高。其实这就是在用算力替代人力。', 'zh')
    for phrase in ('本质上', '值得注意的是', '很显然'):
        assert 'editorial_cliche' in codes(f'{phrase}，美债收益率还在涨。', 'zh'), phrase
    assert 'editorial_cliche' in codes('这次不是流动性问题，而是信用问题。', 'zh')


def test_followup_zh_question_opener_imperative_track_record():
    # fill-run drafts that passed v2 (链上阿树 / 墨川 / 慢慢小鹿)
    assert 'rhetorical_opener' in codes('就因为稍微跌了一下，整个上行的势头就这么断了？比特币的结构没变。', 'zh')
    assert 'rhetorical_opener' not in {f['code'] for f in es.findings('谁在接盘？', 'zh', post_format='question')}
    assert 'rhetorical_opener' not in codes('美股高位全靠利润预期硬扛。\n\n财报季市场拿什么兜底？', 'zh')
    assert 'trade_imperative' in codes('上升趋势没断。少在短线里来回折腾，大行情还在后头。', 'zh')
    assert 'fabricated_experience' in codes('我一直坚持股优于债。', 'zh')
    assert codes('我认为股优于债。', 'zh') == set()


def test_research_tone_and_short_posts():
    long = '这是一句非常非常长而且没有任何停顿的研报式句子它把背景机制结论和后续观察点全部塞在一起读起来像卖方晨会纪要一样累人。'
    assert 'research_tone' in codes(long, 'zh')
    assert codes('L2 估值在往下掉。\n钱都去了 AI。\n没有退出通道的板块会先被抛。', 'zh') == set()
    # fill run 20261007T102226: a 34-char one-liner with commas is a call, not a research note
    assert codes('纯讲故事的空叙事终于开始退潮，Abstract 关门就是信号，没有 PMF 的公链会先被出清。', 'zh') == set()
    two = '萨尔瓦多为配合IMF取消了比特币强制支付这件事本身说明政府在压力下愿意让步。用加密钱包走的汇款占比只有百分之一点七五这个数字太小了根本撑不起流动性。'
    assert 'research_tone' in codes(two, 'zh')


def test_first_person_experience_but_opinions_pass():
    assert 'fabricated_experience' in codes('我上周抄底了一点，账户还在亏。', 'zh')
    assert 'fabricated_experience' in codes('如果你看过我的直播就知道我早说过。', 'zh')
    assert 'fabricated_experience' in codes('I bought more last week and my position is green.', 'en')
    assert codes('我觉得这轮回调还没完。', 'zh') == set()
    assert codes("I'm not convinced the ramp holds.", 'en') == set()
    assert 'fabricated_experience' not in {f['code'] for f in es.findings('我买了', 'zh', first_person_allowed=True)}


def test_en_clichés_overclaim_and_trade_imperatives():
    assert 'en_cliche' in codes("Here's the thing: yields are not done.", 'en')
    assert 'en_cliche' in codes('Yields keep climbing.\nStay tuned.', 'en')
    assert 'en_cliche' in codes("This isn't just a domestic tantrum. It's a global selloff.", 'en')
    assert 'overclaim' in codes('The 6% print looks like a done deal.', 'en')
    assert 'trade_imperative' in codes('Funding reset. Buy the dip.', 'en')
    assert 'trade_imperative' not in codes('Sell-side estimates are too high. Buy-side is skeptical.', 'en')
    assert codes('RPM: narrowed guidance is drowning out the beat.\n\nThe test is whether sales stabilise.', 'en') == set()


def test_style_codes_are_hard_with_fixes():
    for code in es.CODES:
        assert code in qa_levels.HARD and code in qa_levels.FIXES
    assert qa_levels.draft_status(qa_levels.classify([{'code': 'overclaim', 'detail': 'x'}], frame_found=True)) \
        == 'needs_review'


def test_beat_gate():
    momo, xiaolu, basil, kestrel = (ACCOUNTS[a] for a in ('zh_us_stocks', 'zh_longterm_investing', 'crypto_thesis_en',
                                                           'crypto_trader_en'))
    assert not es.beat_gate(momo, 'GenLayer 代币上线，链上 AI Agent 流动性爆发')[0]
    assert not es.beat_gate(xiaolu, '加密行业洗牌，L2 公链估值下移，币圈大户撤资')[0]
    assert es.beat_gate(momo, 'AI 推理 token 用量翻倍，ASIC 和光模块供不应求')[0]   # LLM tokens are not crypto
    assert not es.beat_gate(basil, 'Equities walk a tightrope as long-bond yields hit multi-decade highs')[0]
    assert not es.beat_gate(kestrel, 'Midterm VIX curve sits below prior setups; systematic positioning is high')[0]
    assert es.beat_gate(kestrel, 'Bitcoin longs liquidated as funding resets')[0]
    assert es.beat_gate(ACCOUNTS['crypto_macro_zh'], '美债收益率创新高，流动性收紧')[0]   # macro crypto account


def test_title_event_groups_two_outlets():
    import daily_compose as dc
    a = dc.title_event('Robinhood adds $25 million worth of bitcoin to balance sheet as it deepens crypto push (part 1/1)')
    b = dc.title_event('Robinhood adds bitcoin worth $25 million to its balance sheet (part 1/1)')
    assert a == b
    assert dc.title_event('Bitcoin briefly slides below $84,000') != dc.title_event('Bitcoin nears highest level since January')
    assert dc.title_event('Hi') is None


def test_audit_supersedes_and_fill_counts_ready_only(tmp_path, monkeypatch):
    import apply_inbox_audit
    import daily_compose as dc
    monkeypatch.setenv('FD_COMPOSE_INBOX', str(tmp_path))
    day = '2026-10-07'
    base = {'day': day, 'draft_status': 'draft_ready', 'held': False, 'text': 'x', 'body': 'x', 'angle': {'id': 'a'}}
    compose_inbox.add({**base, 'id': 'd1', 'account_id': 'zh_us_stocks', 'source': {'id': 's1', 'title': 'GenLayer'}})
    compose_inbox.add({**base, 'id': 'd2', 'account_id': 'zh_us_stocks', 'source': {'id': 's2', 'title': 'L2 估值'}})
    compose_inbox.add({**base, 'id': 'd3', 'account_id': 'zh_industry', 'source': {'id': 's3', 'title': 'HBM'}})
    counts = apply_inbox_audit.apply({'day': day, 'reviewer': 't', 'verdicts': {
        'd1': ['drop', 'off-beat'], 'd2': ['rewrite', 'thin'], 'd3': ['keep', 'ok']}})
    assert counts == {'keep': 1, 'rewrite': 1, 'drop': 1}
    d = date.fromisoformat(day)
    assert dc.drafted_today(d) == {'zh_us_stocks': 2, 'zh_industry': 1}
    assert dc.drafted_today(d, ready_only=True) == {'zh_industry': 1}
    assert dc.superseded_sources(d) == {'zh_us_stocks': {'s2', 'L2 估值'}}
    assert {e[1] for e in dc.ready_events(d, list(ACCOUNTS.values()))} == {'zh_industry'}
    row = compose_inbox.get('d1')
    assert row['superseded'] and row['held'] and row['review_status'] == 'pending'


def test_ops_page_x_weight_and_status():
    import build_ops_dashboard as ops
    assert ops.x_weight('abc') == 3
    assert ops.x_weight('比特币。') == 8            # CJK and full-width punctuation weigh 2
    assert ops.x_weight("Bitcoin’s") == 9           # curly apostrophe weighs 1
    assert ops.x_weight('…') == 2
    assert ops.x_weight('see https://example.com/x') == 4 + 23
    assert ops.status_of({'superseded': True, 'held': True}) == 'superseded'
    assert ops.status_of({'held': True, 'draft_status': 'needs_review'}) == 'HOLD'
    assert ops.status_of({'draft_status': 'draft_ready'}) == 'draft_ready'
    assert ops.note_of({'superseded': True, 'audit': {'verdict': 'drop', 'reason': '跑题'}}) == '审稿弃用：跑题'
    assert ops.note_of({'held': True, 'hold_reason': 'hard: overclaim'}) == 'hard: overclaim'


def test_recheck_holds_and_requalifies(tmp_path, monkeypatch):
    import apply_inbox_audit
    monkeypatch.setenv('FD_COMPOSE_INBOX', str(tmp_path))
    day = '2026-10-07'
    base = {'day': day, 'lang': 'zh', 'post_format': {'type': 'one_liner'}}
    compose_inbox.add({**base, 'id': 'r1', 'account_id': 'crypto_macro_zh', 'text': 'x', 'held': False,
                       'draft_status': 'draft_ready', 'body': '趋势没断。少在短线里来回折腾。', 'findings': []})
    compose_inbox.add({**base, 'id': 'r2', 'account_id': 'crypto_research_zh', 'text': 'x', 'held': True,
                       'draft_status': 'needs_review', 'body': '纯叙事公链在退潮，Abstract 关门就是信号。',
                       'findings': [{'code': 'research_tone', 'level': 'hard'}]})
    compose_inbox.add({**base, 'id': 'r3', 'account_id': 'crypto_trader_zh', 'text': 'x', 'held': True,
                       'draft_status': 'needs_review', 'body': '多头被清算。', 'arbitration': {'status': 'HOLD'},
                       'findings': [{'code': 'research_tone', 'level': 'hard'}]})
    changed = {c[1]: c[2] for c in apply_inbox_audit.recheck(day)}
    assert changed == {'r1': 'needs_review', 'r2': 'draft_ready'}   # arbitration hold r3 untouched
    assert compose_inbox.get('r1')['held'] and not compose_inbox.get('r2')['held']
