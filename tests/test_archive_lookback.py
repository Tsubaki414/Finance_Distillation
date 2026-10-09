"""live/archive_lookback.py: 回看 gate, ledger, candidates, then-vs-now data, checks, one targeted rewrite, inbox row."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from live import archive_lookback as al, compose_inbox  # noqa: E402

CFG = {'enabled_accounts': ['crypto_altcoin_zh', 'crypto_macro_en'], 'per_day': 1, 'event_cooldown_days': 30,
       'target_ready_per_day': 2, 'min_chars': {'en': 80, 'zh': 30},
       'windows': [{'id': 'feb2025', 'since': '2025-02-01', 'until': '2025-03-01', 'rank': 0},
                   {'id': 'year_ago', 'days_before': 365, 'half_width_days': 10, 'rank': 1}]}
ZH = {'id': 'crypto_altcoin_zh', 'no': 6, 'name': '0xLark', 'beat': '山寨', 'lang': 'zh', 'kind': 'crypto',
      'retrieval_beats': ['crypto_meme', 'crypto_defi']}
EN = {'id': 'crypto_macro_en', 'no': 11, 'name': 'Theo', 'beat': 'Crypto macro', 'lang': 'en', 'kind': 'crypto',
      'retrieval_beats': ['crypto_macro_en']}
STOCKS = {'id': 'zh_us_stocks', 'no': 9, 'name': 'Momo', 'beat': '美股', 'lang': 'zh', 'kind': 'stocks',
          'retrieval_beats': ['single_stock_deepdive_en']}

SOL_TEXT = 'SOL 这波解锁前跌不太下去，130 一线有人接，链上交易量还在，山寨轮动要等 SOL 自己先站稳。'


def _post(pid='1894', text=SOL_TEXT, handle='kiki520_eth', **kw):
    return {'id': pid, 'text': text, 'handle': handle, 'role': 'donor', 'window': 'feb2025', 'window_rank': 0,
            'date': '2025-02-25', 'created_utc': '2025-02-25T10:00:00+00:00', 'rt': False, 'reply': False,
            'self_thread': False, 'views': 100, 'url': f'https://x.com/{handle}/status/{pid}', **kw}


def _rows():
    t0 = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    out = []
    for i in range(650):
        v = 144.33 if i == 55 else (115.52 if i == 649 else 120 + (i % 30))
        out.append((t0 + i * 86400, v))
    return out


def _cand(text=SOL_TEXT):
    c, why = al.eligible(_post(text=text), ZH, CFG)
    assert c, why
    tn = al.then_now(c['subject'], c['date'], rows_fn=lambda s: (_rows(), 'Binance spot', 'https://x', '2026-10-07T21:00:00+00:00', '1d'))
    return {**c, 'tn': tn, 'data_lines': al.data_lines(tn)}


def test_enabled_accounts_flag():
    assert al.enabled_accounts(CFG, {}) == CFG['enabled_accounts']
    assert al.enabled_accounts(CFG, {'FD_ARCHIVE': '1'}) == CFG['enabled_accounts']
    assert al.enabled_accounts(CFG, {'FD_ARCHIVE': '0'}) == []
    shipped = al.load_config()
    assert shipped['enabled_accounts'] == 'all' and len(shipped['pilot_accounts']) == 3 and shipped['per_day'] == 1 and shipped['event_cooldown_days'] == 30


def test_windows_feb_first_then_year_ago():
    w = al.windows(CFG, '2026-10-08')
    assert w[0][:3] == ('feb2025', '2025-02-01', '2025-03-01')
    assert w[1][0] == 'year_ago' and w[1][1] == '2025-09-28' and w[1][2] == '2025-10-19'


def test_gate_per_day_and_gap(tmp_path, monkeypatch):
    monkeypatch.setenv('FD_SLOT_RULE', '0')   # pre-Oct 9 gap rule; the slot rule: tests/test_slot_rule_oct9.py
    monkeypatch.delenv('FD_ARCHIVE', raising=False)
    base = tmp_path / 'inbox'
    ok, why = al.gate('crypto_altcoin_zh', '2026-10-08', config=CFG, timely_planned=1, base=base)
    assert ok and 'gap' in why
    ok, why = al.gate('crypto_altcoin_zh', '2026-10-08', config=CFG, timely_planned=2, base=base)
    assert not ok and 'enough fresh' in why
    assert not al.gate('zh_us_stocks', '2026-10-08', config=CFG, base=base)[0]   # not enabled
    compose_inbox.add({'id': 'arc-1', 'day': '2026-10-08', 'account_id': 'crypto_altcoin_zh', 'text': 'x',
                       'post_kind': al.POST_KIND, 'draft_status': 'draft_ready'}, base=base)
    ok, why = al.gate('crypto_altcoin_zh', '2026-10-08', config=CFG, base=base)
    assert not ok and 'already' in why
    monkeypatch.setenv('FD_ARCHIVE', '0')
    assert not al.gate('crypto_macro_en', '2026-10-08', config=CFG, base=base)[0]


def test_ledger_30_day_cooldown(tmp_path):
    led = tmp_path / 'ledger.jsonl'
    al.record_use('crypto_altcoin_zh', '2026-10-08', ['x:1894', 'k|SOL|2025-02-25'], 'arc-1', path=led)
    assert 'x:1894' in al.used_recently('crypto_altcoin_zh', '2026-11-06', 30, path=led)
    assert not al.used_recently('crypto_altcoin_zh', '2026-11-07', 30, path=led)
    assert not al.used_recently('crypto_macro_en', '2026-10-09', 30, path=led)


def test_candidates_filters_and_used():
    posts = {('k', 'feb2025'): [
        _post('1'), _post('2', reply=True), _post('3', text='gm gm 今天也要加油，大家冲 SOL 冲冲冲，链上见 抽奖 福利'),
        _post('4', text='$RED 今天上了，打新收益不错，这个盘子还会再拉，跟上节奏不要掉队，后面还有更多机会'),
        _post('5', text='英伟达财报前瞻：数据中心收入指引再上调，估值和增速要放在一起看，市场在等下一季指引。')]}
    got = al.candidates(posts, ZH, '2026-10-08', config=CFG)
    assert [c['id'] for c in got] == ['1']           # reply, promo, unknown cashtag, off-beat dropped
    assert got[0]['subject']['symbol'] == 'SOL'
    used = set(al.event_keys(got[0], 'SOL'))
    assert al.candidates(posts, ZH, '2026-10-08', config=CFG, used=used) == []
    stock = al.candidates(posts, STOCKS, '2026-10-08', config=CFG)
    assert [c['id'] for c in stock] == ['5'] and stock[0]['subject']['symbol'] == 'NVDA'


def test_market_extras_subject():
    s = al.subject_of('日元的汇率不可能一直跌下去，会有一个很强的底部阻力线。', ZH)
    assert s['symbol'] == 'JPY=X' and s['unit'] == 'yen'
    assert al.subject_of('make OKX the gold standard of compliance', EN) is None


def test_then_now_and_data_lines():
    c = _cand()
    tn = c['tn']
    assert tn['then'] == {'date': '2025-02-25', 'value': 144.33, 'text': '144.33'}
    assert tn['now']['text'] == '115.52' and tn['change_pct'] == -20.0
    assert c['data_lines'][0].startswith('THEN: SOL daily close on 2025-02-25: 144.33 USD')
    assert 'NOW: SOL latest price as of' in c['data_lines'][1] and c['data_lines'][2].startswith('CHANGE: -20.0%')
    short = al.then_now(c['subject'], '2025-02-25', rows_fn=lambda s: (_rows()[-30:], 'x', 'u', 'f', '1d'))
    assert short is None                               # history does not reach the old date


GOOD = ('回看｜2025年2月，@kiki520_eth 写过“130 一线有人接”。\n'
        '当时 SOL 收在 144.33 美元，今天是 115.52 美元，跌了 20.0%。\n'
        '一年多过去，支撑位的说法没有挡住下跌，山寨轮动更要看 SOL 自己。')


def test_check_good_draft_has_no_hard_findings():
    found, rows = al.check(GOOD, _cand(), ZH)
    assert not [f for f in found if f['level'] == 'hard'], found
    assert rows and any(r['kind'] == 'number' for r in rows)


@pytest.mark.parametrize('body,code', [
    (GOOD.replace('130 一线有人接', '130 一线一定守得住'), 'archive_quote_not_verbatim'),
    (GOOD.replace('回看｜', ''), 'archive_framing'),
    (GOOD.replace('115.52', '99.10'), 'ungrounded_number'),
    (GOOD.replace('一年多过去', '我早就说过，一年多过去'), 'fabricated_experience'),
    ('回看｜2025年2月 @kiki520_eth 说 130 一线有人接。今天 SOL 144.33 美元，还在原地。', 'archive_stale_as_current'),
])
def test_check_hard_codes(body, code):
    found, _ = al.check(body, _cand(), ZH)
    assert code in {f['code'] for f in found if f['level'] == 'hard'}, found


class FakeClient:
    def __init__(self, bodies):
        self.bodies, self.calls, self.messages = list(bodies), [], []

    def __call__(self, stage, messages, max_tokens):
        assert stage == 'compose'
        self.messages.append(messages)
        body = self.bodies.pop(0)
        return {'text': json.dumps({'pick': '1894', 'body': body, 'quotes': ['130 一线有人接'], 'why': 'w'}),
                'response_model': 'gemini-3.1-pro-preview'}


def test_compose_one_targeted_rewrite_then_ready():
    bad = GOOD.replace('回看｜', '')
    fc = FakeClient([bad, GOOD])
    r = al.compose(fc, ZH, [_cand()], '2026-10-08')
    assert r['status'] == 'draft_ready' and r['body'] == GOOD and r['attempts'] == 2
    assert r['hard_repair']['first_codes'] == ['archive_framing'] and r['hard_repair']['retry_codes'] == []
    note = json.loads(fc.messages[1][-1]['content'])['editor_note']
    assert note.startswith('[hard_repair]') and 'archive_framing' in note


def test_compose_still_hard_after_rewrite_is_held():
    bad = GOOD.replace('回看｜', '')
    r = al.compose(FakeClient([bad, bad]), ZH, [_cand()], '2026-10-08')
    assert r['status'] == 'needs_review' and r['hard'] == ['archive_framing'] and r['attempts'] == 2


def test_compose_none_pick():
    class NoneClient(FakeClient):
        def __call__(self, stage, messages, max_tokens):
            return {'text': '{"pick": "NONE", "body": "", "why": "nothing worth it"}',
                    'response_model': 'gemini-3.1-pro-preview'}
    r = al.compose(NoneClient([]), ZH, [_cand()], '2026-10-08')
    assert r['status'] == 'none' and not r['body']


def test_inbox_row_label_url_and_dashboard(tmp_path):
    r = al.compose(FakeClient([GOOD]), ZH, [_cand()], '2026-10-08')
    row = al.inbox_row(r, ZH, '2026-10-08', 'arc20261008T000000', post_time='2026-10-08T09:30:00+01:00')
    assert row['post_kind'] == 'archive_lookback' and row['label'] == '回看' and not row['held']
    assert row['archive']['original_url'] == 'https://x.com/kiki520_eth/status/1894'
    assert row['archive']['then_vs_now']['then']['text'] == '144.33' and row['publishable'] is False
    row['media'] = [al.attach_chart(row, r['cand']['tn'], tmp_path)]
    assert (tmp_path / row['media'][0]['path']).stat().st_size > 1000
    assert row['media'][0]['kind'] == 'archive_chart'    # scripts/refresh_charts.py only refreshes kind 'chart'
    import build_ops_dashboard as ops
    m = ops.media_of(row)
    assert m['archive'] is True and m['archive_url'].endswith('/1894') and m['media'][0]['path'].endswith('.png')
    from backend.compose_inbox import render
    assert '【回看】' in render([compose_inbox.add(row, base=tmp_path / 'inbox')], '2026-10-08')


def test_plain_language_exempts_subject_ticker_and_verbatim_quote_only():
    text = 'Sui 上借贷有补贴，由于有SUI的补贴支撑，等于Sui官方在帮Scallop赚钱，借 USDC 基本无息，SCA 也有补贴。'
    c, _ = al.eligible(_post(text=text, handle='chenmo'), ZH, CFG)
    tn = al.then_now(c['subject'], c['date'], rows_fn=lambda s: (_rows(), 'Binance spot', 'u', 'f', '1d'))
    c = {**c, 'tn': tn, 'data_lines': al.data_lines(tn)}
    body = ('回看｜2025年2月，@chenmo 写过“由于有SUI的补贴支撑”。当时价格 144.33 美元，今天 115.52 美元，跌了 20.0%。'
            '补贴撑起来的资金池，外部输血一停就难留住。')
    assert 'jargon_unexplained' not in {f['code'] for f in al.check(body, c, ZH)[0]}
    worse = body.replace('补贴撑起来的资金池', 'XYZQ 补贴撑起来的资金池')
    left = [f for f in al.check(worse, c, ZH)[0] if f['code'] == 'jargon_unexplained']
    assert left and left[0]['detail'] == 'XYZQ' and left[0]['level'] == 'hard'


def test_recheck_releases_and_holds(tmp_path, monkeypatch):
    raw = tmp_path / 'raw'
    monkeypatch.setenv('FD_ARCHIVE_RAW', str(raw))
    page = {'result': {'timeline': {'instructions': [{'entries': [{'content': {'itemContent': {'tweet_results': {'result': {
        'rest_id': '1894', 'legacy': {'full_text': SOL_TEXT, 'user_id_str': '9', 'created_at': 'Tue Feb 25 10:00:00 +0000 2025',
                                      'lang': 'zh'}}}}}}]}]}}}
    (raw / 'raw' / 'kiki520_eth').mkdir(parents=True)
    (raw / 'raw' / 'kiki520_eth' / 'feb2025.json').write_text(json.dumps(page))
    r = al.compose(FakeClient([GOOD]), ZH, [_cand()], '2026-10-08')
    row = al.inbox_row(r, ZH, '2026-10-08', 'arc20261008T000000', post_time='2026-10-08T09:30:00+01:00')
    base = tmp_path / 'inbox'
    compose_inbox.add({**row, 'held': True, 'hold_reason': 'hard: ungrounded_number', 'draft_status': 'needs_review'},
                      base=base)
    accts = tmp_path / 'accounts.json'
    accts.write_text(json.dumps({'accounts': [ZH]}))
    out = al.recheck('2026-10-08', base=base, accounts_path=accts, log=lambda *_: None)
    assert out[0]['hard'] == []
    stored = compose_inbox.get(row['id'], base=base)
    assert stored['draft_status'] == 'draft_ready' and not stored['held'] and stored['text'] == GOOD
    assert stored['rechecks'][0]['before'] == [True, 'hard: ungrounded_number']


def test_draft_media_leaves_archive_chart_alone(tmp_path):
    from live import draft_media
    row = {'id': 'arc-x', 'day': '2026-10-08', 'post_kind': 'archive_lookback', 'text': GOOD,
           'media': [{'kind': 'archive_chart', 'path': 'media/2026-10-08/arc-x.png'}]}
    assert draft_media.annotate(dict(row), ZH, tmp_path)['media'] == row['media']
