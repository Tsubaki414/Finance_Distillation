"""Oct 12 (Fiona): explainer post type (live/explainer_mix.py) + opener quotas / bans (live/opener_mix.py)."""
from datetime import datetime, timedelta, timezone

from live import explainer_mix as xm, fresh_hold, opener_mix as om, posting_habits as ph


# ---------------------------------------------------------------- explainer
def test_kill_switches(monkeypatch):
    monkeypatch.setenv('FD_EXPLAINER', '0')
    monkeypatch.setenv('FD_OPENER_MIX', '0')
    assert not xm.enabled() and not om.enabled()
    assert om.fix_opener('我看 美债要涨', 'zh') == ('我看 美债要涨', [])
    assert om.first_hand_findings('亲测年化11%', 'zh') == []
    assert om.Planner().assign('zh_macro', 'zh', {}, {'type': 'one_liner'}, None) is None


def test_donor_classifier():
    zh = '质押怎么做：\n1. 先在官网确认合约地址\n2. 存入 32 ETH\n3. 等待 27 小时激活\n收益约 3.2%。' + '说明' * 40
    assert xm.is_explainer_text(zh, 'zh')
    assert not xm.is_explainer_text('大饼又跌了，麻了', 'zh')
    en = ("Here's how the vault works:\n1. deposit USDC\n2. it lends on Aave at 4.1%\n3. rewards auto-compound "
          "every 8h\nThat is the whole loop." + ' filler' * 20)
    assert xm.is_explainer_text(en, 'en')


def test_account_allowed_zh_always_en_by_donor_share(monkeypatch):
    monkeypatch.setitem(xm._SHARE_CACHE, 'd', {'defi_narratives_en': {'share': 0.18}, 'crypto_meme_en': {'share': 0.01}})
    assert xm.account_allowed('zh_macro', 'zh', '2026-10-13')
    assert xm.account_allowed('defi_narratives_en', 'en', '2026-10-13')   # 7 x 0.18 >= 1: daily
    assert not xm.account_allowed('crypto_meme_en', 'en', '2026-10-13')


def test_pick_ok_rules():
    base = {'numbers': 3, 'timely': True, 'source_id': 'ch1-abc'}
    assert xm.pick_ok(base)
    assert not xm.pick_ok(dict(base, numbers=1))
    assert xm.pick_ok(dict(base, timely=False))   # fresh_hold (48 h) is the gate, not the 30 h 'timely' flag
    assert not xm.pick_ok(dict(base, lookback_frame=True))
    assert not xm.pick_ok(dict(base, kind='diary'))
    assert not xm.pick_ok(dict(base, source_id='x-123'))
    assert not xm.pick_ok(dict(base, source_id='arc-1'))


def test_post_format_and_block():
    f = xm.post_format('zh')
    assert f['explainer'] and f['no_nat'] and f['length_target']['min'] >= 200

    class P:
        lang, persona_id = 'zh', 'acct_zh_macro'
    import importlib
    import live.posting_habits as _ph
    importlib.reload(_ph)   # some earlier suites leave posting_habits in a state that drops kind blocks (pre-existing)
    blk = _ph.format_block(P(), f, card={'per_type_habits': {}, 'punctuation': {}}, posts_dir='/nonexistent')
    assert blk['kind'] == 'explainer' and '亲测' in blk['explainer_rule'] and '200' in blk['explainer_rule']


def test_done_today_counts_only_ready_explainers():
    rows = [{'account_id': 'a', 'day': '2026-10-13', 'explainer': True},
            {'account_id': 'a', 'day': '2026-10-13', 'explainer': True, 'held': True},
            {'account_id': 'b', 'day': '2026-10-13', 'explainer': True}]
    assert xm.done_today('a', rows, '2026-10-13') == 1


def test_explainer_findings_soft():
    body = '今天这件事讲清楚：\n1. 第一步 32 ETH\n2. 第二步 27 小时\n' + '解释' * 100
    assert xm.body_findings(body, 'zh', {'explainer': True}) == []
    f = xm.body_findings('太短了', 'zh', {'explainer': True})
    assert {x['code'] for x in f} == {'explainer_too_short', 'explainer_no_steps', 'explainer_no_numbers'}
    assert all(x['level'] == 'soft' for x in f)
    assert xm.body_findings('太短了', 'zh', {}) == []


def test_explainer_row_gets_no_fresh_hold_exemption():
    """Explicit: an explainer row is a normal news row for fresh_hold (48 h source age applies)."""
    slot = datetime(2026, 10, 13, 9, tzinfo=timezone.utc)
    row = {'id': 'compose-x', 'post_type': 'judgment_take', 'explainer': True,
           'post_format': xm.post_format('zh'), 'suggested_post_time_london': slot.isoformat(),
           'source': {'published_at': (slot - timedelta(hours=60)).isoformat()}, 'body': '1. a\n2. b'}
    assert not fresh_hold.is_archive_row(row)
    hold, why, _ = fresh_hold.check(row, env={'FD_FRESH_HOLD': '1'})
    assert hold and 'stale_source' in str(why)
    row['source']['published_at'] = (slot - timedelta(hours=20)).isoformat()
    assert fresh_hold.check(row, env={'FD_FRESH_HOLD': '1'})[0] is False


# ---------------------------------------------------------------- openers
def test_zh_question_quota_paced():
    pl = om.Planner()
    got = [pl.assign('zh_macro', 'zh', {}, {'type': 'one_liner'}, None) for _ in range(20)]
    share = got.count('question') / 20
    assert 0.15 <= share <= 0.20


def test_breaking_only_fresh_en_macro_and_capped():
    slot = datetime(2026, 10, 13, 9, tzinfo=timezone.utc)
    fresh = {'published_at': (slot - timedelta(hours=2)).isoformat(), 'numbers': 2}
    stale = {'published_at': (slot - timedelta(hours=9)).isoformat(), 'numbers': 2}
    pl = om.Planner()
    assert pl.assign('crypto_macro_en', 'en', stale, {'type': 'one_liner'}, slot) is None
    assert pl.assign('crypto_meme_en', 'en', fresh, {'type': 'one_liner'}, slot) is None   # not a macro account
    assert pl.assign('crypto_macro_en', 'en', fresh, {'type': 'one_liner'}, slot) == 'breaking'
    assert pl.assign('crypto_macro_en', 'en', fresh, {'type': 'one_liner'}, slot) is None   # 1 per account
    pl.assign('market_data_charts', 'en', fresh, {}, slot)
    pl.assign('investing_philosophy', 'en', fresh, {}, slot)
    assert pl.assign('single_stock_deepdive_en', 'en', fresh, {}, slot) is None             # day cap 3


def test_zh_banned_openers_stripped():
    assert om.fix_opener('我看 Microsoft 在决策上有优势。', 'zh')[0] == 'Microsoft 在决策上有优势。'
    assert om.fix_opener('我觉得AI会挤压白领', 'zh')[0] == 'AI会挤压白领'
    assert om.fix_opener('DefiLlama：发射平台手续费合计$4.5m', 'zh')[0] == '发射平台手续费合计$4.5m'
    assert om.fix_opener('（来源：Glassnode）短期抛压很重', 'zh')[0] == '短期抛压很重'
    assert om.fix_opener('我看了下数据，ETH 流出', 'zh')[1] == []          # real observation verb, not the tic
    assert om.fix_opener('我看好这条赛道', 'zh')[1] == []
    assert om.fix_opener('结论：先别追', 'zh')[1] == []                    # not a source label
    body = '大饼又跌\n（来源：Glassnode）'
    assert om.fix_opener(body, 'zh')[0] == body                              # footer credit untouched


def test_en_breaking_stripped_unless_assigned_and_fresh():
    b = '🚨 US 10Y YIELD HITS 5.3%.\nBonds are cracking.'
    assert om.fix_opener(b, 'en', 'breaking', 2.0) == (b, [])
    out, ch = om.fix_opener(b, 'en', None, 2.0)
    assert out.startswith('US 10Y') and ch
    out, ch = om.fix_opener('BREAKING: CPI 3.1%\nHot.', 'en', 'breaking', 9.0)
    assert out.startswith('CPI') and ch


def test_first_hand_hard_on_all_drafts():
    for body, lang in (('亲测这个池子年化 11%', 'zh'), ('我朋友跟我说他满仓了', 'zh'), ('我昨天买了 2 个 ETH', 'zh'),
                       ('I tried the new vault and it pays 9%', 'en'), ('My friend at a fund says', 'en'),
                       ("I'm up $40k on this", 'en')):
        f = om.first_hand_findings(body, lang)
        assert f and f[0]['level'] == 'hard' and f[0]['code'] == 'invented_first_hand', body
    assert om.first_hand_findings('我觉得这个池子收益不可持续', 'zh') == []
    assert om.first_hand_findings('Funding flipped negative at 0.01%', 'en') == []


def test_opener_class():
    assert om.opener_class('美债会崩吗？\n不会', 'zh') == 'question'
    assert om.opener_class('我看要跌', 'zh') == 'stock_wo_kan'
    assert om.opener_class('DefiLlama：TVL 120亿', 'zh') == 'source_label'
    assert om.opener_class('🚨 CPI HOT', 'en') == 'breaking'
    assert om.opener_class('Funding is negative.', 'en') == 'assertion'


def test_split_steps():
    b = '拆解：\n\n1. 做市商回流，深度高75%。2. 以太坊深度翻倍至420万美元。3. 现货周均2790亿美元。'
    out = xm.split_steps(b)
    assert '\n\n2. 以太坊' in out and '\n\n3. 现货' in out and '420万' in out
    assert xm.split_steps('涨了2.5%。') == '涨了2.5%。'
