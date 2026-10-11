"""Oct 11 (Fiona, 墨川.eth 10-11 22:37): an event > 30 days old needs a look-back frame + today comparison
(live/stale_frame.py, HARD stale_event_unframed), and BTC/ETH macro accounts only take on-lane material - off-lane
packets / archive picks are reassigned to the account whose lane fits (live/lane_fit.macro_check / archive_check)."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from live import humanize, lane_fit, qa_levels, stale_frame  # noqa: E402

DAY = '2026-10-11'
TETHER = ('稳定币随时面临单边切断的风险，Tether 封锁账户全靠内部定夺。\n\n'
          '我看到 2025年9月24日 他们仅凭名单，按内部标准冻结了 276万美元 营运资金。')
TETHER_SRC = ('Payments Firm Says Tether Froze $2.76 Million Brazilian Police Didn’t Flag, Forcing Layoffs. '
              'Tether froze $2.76 million of a payments company’s working capital; the wallet has been frozen since '
              'Sept. 24, 2025, according to the complaint, filed Oct. 5. Tether’s T3 Financial Crime Unit decided which '
              'wallets to freeze using its own criteria.')

MACRO_ZH = {'id': 'crypto_macro_zh', 'lang': 'zh', 'retrieval_beats': ['crypto_macro_zh', 'crypto_macro_en']}
MACRO_EN = {'id': 'crypto_macro_en', 'lang': 'en', 'retrieval_beats': ['crypto_macro_en']}
CYCLES_EN = {'id': 'btc_cycles_en', 'lang': 'en', 'retrieval_beats': ['crypto_macro_en', 'crypto_onchain']}
STABLE_ZH = {'id': 'crypto_stable_yield_zh', 'lang': 'zh', 'lane_first': True,
             'retrieval_beats': ['crypto_stable_yield', 'crypto_defi', 'crypto_macro_zh']}
STABLE_EN = {'id': 'crypto_stable_yield_en', 'lang': 'en', 'lane_first': True,
             'retrieval_beats': ['crypto_stable_yield', 'crypto_defi', 'crypto_macro_en']}
AIRDROP_EN = {'id': 'crypto_airdrop_en', 'lang': 'en', 'lane_first': True,
              'retrieval_beats': ['crypto_airdrop', 'crypto_defi', 'crypto_perp', 'crypto_macro_en']}
ROSTER = [MACRO_ZH, MACRO_EN, CYCLES_EN, STABLE_ZH, STABLE_EN, AIRDROP_EN]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ stale_frame

def test_year_old_event_without_frame_is_hard():
    f = stale_frame.findings(TETHER, 'zh', DAY)
    assert [x['code'] for x in f] == ['stale_event_unframed'] and f[0]['level'] == 'hard'
    assert '2025-09-24' in f[0]['detail'] and 'look-back frame' in f[0]['detail']
    assert 'stale_event_unframed' in qa_levels.HARD and qa_levels.FIXES['stale_event_unframed']
    assert qa_levels.level({'code': 'stale_event_unframed'}, frame_found=True) == 'hard'


def test_look_back_frame_and_today_comparison_pass():
    assert stale_frame.ok('回看：去年9月24日 Tether 冻结了 276万美元。如今同类诉讼才刚上法院。', DAY)
    assert stale_frame.ok('Look back: Oct 2025.\n\nIn October 2025, @x noted BTC hit $125k. As of 2026-10-11 it sits at $82,989.', DAY)
    # an archive draft needs the frame AND the today comparison; a standalone needs the frame
    assert not stale_frame.ok('回看：2025年9月24日 Tether 冻结了 276万美元。', DAY, archive=True)
    assert stale_frame.ok('回看：2025年9月24日 Tether 冻结了 276万美元。', DAY)
    assert not stale_frame.ok('现在稳定币风险很大：2025年9月24日 Tether 冻结了 276万美元。', DAY)
    # history wording in an explainer is a frame (background, not news)
    assert stale_frame.ok('逆回购此前在2023年初达到约25000亿美元的峰值，随后缩表回落。', DAY)
    assert not stale_frame.ok('In September 2025, Tether froze $2.76M of working capital.', DAY)


def test_recent_dates_and_reference_periods_are_not_events():
    assert stale_frame.ok('10月5日近四分之三的供应处于盈利状态', DAY)
    assert stale_frame.ok('看跌对看涨比率处于 2026 年以来的偏低位置', DAY)
    assert stale_frame.ok('ETF 资金自2024年起累计流入 600 亿美元', DAY)
    assert stale_frame.ok('Funding is the lowest since 2023.', DAY)
    assert stale_frame.ok('2025年同期只有一半', DAY)
    assert stale_frame.ok('On Sept. 20, 2026 the Fed cut rates.', DAY)   # 21 days: within the 30-day window
    assert not stale_frame.ok('2024年 Tether 冻结了地址', DAY)          # year-only, > 30 days


def test_stale_frame_switch(monkeypatch):
    monkeypatch.setenv('FD_STALE_FRAME', '0')
    assert stale_frame.findings(TETHER, 'zh', DAY) == []


def test_humanize_reverts_an_edit_that_drops_the_today_comparison(monkeypatch):
    body = '回看：去年9月24日 Tether 冻结了 276万美元 营运资金。\n\n名单之外的钱也被冻结。\n\n如今这家公司才起诉，稳定币的单边冻结风险还在。'
    monkeypatch.setattr(humanize, 'drop_moral_line',
                        lambda b, lang: (b.rsplit('\n\n', 1)[0], b.rsplit('\n\n', 1)[1]))
    monkeypatch.setattr(humanize, 'llm_enabled', lambda: False)
    row = {'id': 'arc-t', 'post_kind': 'archive_lookback', 'account_id': 'crypto_macro_zh', 'day': DAY, 'body': body,
           'text': body}
    humanize.apply(row, client=None, lang='zh', rates={'formula_closer': 0.0, 'intensifier': 1.0, 'precise_number': 1.0})
    assert row['body'] == body
    assert row['humanize']['changes'] == ['REVERTED(frame): look-back frame / today comparison dropped']


# ------------------------------------------------------------------ BTC/ETH macro lane + reassign

def test_macro_lane_rejects_stablecoin_compliance_and_names_the_stable_account():
    chk = lane_fit.macro_check(MACRO_ZH, TETHER_SRC, ROSTER)
    assert not chk['ok'] and chk['reassign']['account'] == 'crypto_stable_yield_zh'
    body = lane_fit.macro_draft_check(MACRO_ZH, TETHER, ROSTER)   # "276万美元" is an amount, not the dollar
    assert not body['ok'] and body['reassign']['account'] == 'crypto_stable_yield_zh'
    assert lane_fit.macro_check(MACRO_ZH, '比特币期权看涨支出比看跌多 1700万美元', ROSTER)['ok']
    assert lane_fit.macro_check(MACRO_ZH, '稳定币供应扩张，流动性回到加密市场', ROSTER)['ok']   # stablecoins as liquidity
    assert lane_fit.macro_check(CYCLES_EN, 'Short-term charts lose perspective during volatile cycles.', ROSTER)['ok']
    assert lane_fit.macro_check(STABLE_ZH, TETHER_SRC, ROSTER)['ok']   # not a macro account


def test_macro_lane_switch(monkeypatch):
    monkeypatch.setenv('FD_MACRO_LANE', '0')
    assert lane_fit.macro_check(MACRO_ZH, TETHER_SRC, ROSTER)['ok']


def test_lane_gate_hands_off_lane_macro_packets_to_the_fitting_account(monkeypatch):
    dc = _script('daily_compose')
    monkeypatch.setattr(dc, 'used_sources', lambda account: set())

    def g(i, title):
        return [{'unit_id': f'u{i}', 'source': {'id': f's{i}', 'title': title, 'adapter': 'rss', 'url': ''},
                 'unit': {'statement': title, 'numbers': []}}]
    pools = {'crypto_macro_zh': [g(1, TETHER_SRC), g(2, 'Bitcoin options lean bullish as ETF inflows return')],
             'crypto_stable_yield_zh': [g(3, 'Ethena sUSDe yield drops to 6% APY')]}
    info = {}
    dc.lane_gate(pools, [MACRO_ZH, STABLE_ZH], {}, info)
    assert [x[0]['source']['id'] for x in pools['crypto_macro_zh']] == ['s2']
    assert [x[0]['source']['id'] for x in pools['crypto_stable_yield_zh']] == ['s3', 's1']   # handed over, kept
    rej = info['off_lane_rejects']['crypto_macro_zh']
    assert rej['rejected'] == 1 and rej['reassigned'][0]['to'] == 'crypto_stable_yield_zh'


def test_archive_pick_lane_check_and_reassign_queue(tmp_path, monkeypatch):
    from live import archive_lookback as al, archive_evergreen as ae
    monkeypatch.setenv('FD_ARCHIVE_STORE', str(tmp_path))
    post = {'id': '777', 'handle': 'donor', 'date': '2025-10-01', 'rt': False, 'reply': False, 'quote': False,
            'text': 'Tether 又冻结了一批地址，稳定币发行方的合规名单完全由自己定，USDT 持有人要清楚这一点，冻结不需要法院。'}
    cfg = {'min_chars': {'zh': 30, 'en': 80}, 'evergreen': {'min_chars': {'zh': 30, 'en': 80}}}
    c, why = al.eligible(post, MACRO_ZH, cfg)
    assert c is None and why == 'off_lane -> crypto_stable_yield_zh'
    assert al.hand_over(DAY, MACRO_ZH, post, why, 'then_vs_now')['to'] == 'crypto_stable_yield_zh'
    assert al.hand_over(DAY, MACRO_ZH, post, why, 'then_vs_now') is None   # once per post and target
    got = al.reassigned_posts(DAY, 'crypto_stable_yield_zh')
    assert [p['id'] for p in got] == ['777'] and got[0]['reassigned_from'] == 'crypto_macro_zh'
    assert al.reassigned_posts(DAY, 'crypto_macro_zh') == []
    c, why = ae.eligible(post, MACRO_ZH, cfg)
    assert c is None and why.startswith('off_lane -> ')


def test_archive_check_niche_broad_pick_goes_to_the_macro_account():
    btc = 'BTC reached a new ATH of $125k and ETF inflows hit a record.'
    chk = lane_fit.archive_check(AIRDROP_EN, btc, ROSTER)
    assert not chk['ok'] and chk['reassign']['account'] == 'crypto_macro_en'
    assert lane_fit.archive_check(AIRDROP_EN, btc + ' Farming seasons priced at the peak rarely hold.', ROSTER)['ok']


# ------------------------------------------------------------------ stored drafts: recheck

def test_recheck_holds_stored_unframed_and_off_lane_drafts(tmp_path):
    aia = _script('apply_inbox_audit')
    d = tmp_path / DAY
    d.mkdir()
    rows = {
        'compose-a': {'account_id': 'crypto_macro_zh', 'lang': 'zh', 'body': TETHER, 'post_mode': 'original'},
        'compose-b': {'account_id': 'crypto_macro_zh', 'lang': 'zh', 'post_mode': 'original',
                      'body': '比特币期权这边，真金白银买涨的钱明显占了上风。看跌对看涨比率压到 0.56，处于 2026 年以来的偏低位置。'},
        'compose-c': {'account_id': 'crypto_macro_zh', 'lang': 'zh', 'post_mode': 'original',
                      'body': '稳定币发行方随时可以冻结地址，Tether 的名单全靠内部标准。'},
    }
    for i, r in rows.items():
        (d / f'{i}.json').write_text(json.dumps({'id': i, 'day': DAY, 'held': False, 'draft_status': 'draft_ready',
                                                 'findings': [], **r}, ensure_ascii=False))
    changed = {c[1]: c[3] for c in aia.recheck(DAY, base=tmp_path)}
    assert changed['compose-a'].startswith('hard: ') and 'stale_event_unframed' in changed['compose-a']
    assert 'compose-b' not in changed
    assert changed['compose-c'].startswith('off_lane: ') and 'crypto_stable_yield_zh' in changed['compose-c']


def test_stablecoin_issuer_risk_is_on_the_stable_yield_lane():
    assert lane_fit.packet_check(STABLE_ZH, TETHER_SRC)['ok']        # freeze / counterparty risk, no yield word needed
    assert lane_fit.packet_check(STABLE_EN, 'Circle blacklisted 3 addresses holding USDC')['ok']
    assert not lane_fit.packet_check(STABLE_ZH, 'Polygon taps TRON stablecoin supply for cross-border transfers')['ok']
