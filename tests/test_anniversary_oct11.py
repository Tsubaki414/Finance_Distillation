"""Oct 11 (Fiona): well-known dated events (10/10 crash one year on, whitepaper, halvings, Lehman ...) were in none of
our sources. live/event_calendar.json + live/anniversary.py surface 1/2/5/10-year anniversaries as packets for fitting
accounts with then-vs-now data, story dedupe and the lane allowlist; drafts are framed (stale_frame) and grounded."""
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from live import anniversary as an, stale_frame  # noqa: E402

CAL = json.loads((ROOT / 'live' / 'event_calendar.json').read_text())
CRASH = next(e for e in CAL['events'] if e['id'] == 'crash_2025_10_10')
ACCTS = {
    'crypto_macro_zh': {'id': 'crypto_macro_zh', 'lang': 'zh', 'name': '墨川', 'beat': '加密宏观 · BTC/ETH 大势判断',
                        'retrieval_beats': ['crypto_macro_zh']},
    'crypto_macro_en': {'id': 'crypto_macro_en', 'lang': 'en', 'name': 'Theo', 'beat': 'Crypto macro · BTC/ETH big picture',
                        'retrieval_beats': ['crypto_macro_en']},
    'crypto_trader_zh': {'id': 'crypto_trader_zh', 'lang': 'zh', 'name': '岑哥', 'beat': '交易员复盘 · K线点位与仓位',
                         'retrieval_beats': ['crypto_trader_zh']},
    'crypto_trader_en': {'id': 'crypto_trader_en', 'lang': 'en', 'name': 'Kestrel', 'beat': 'Crypto trading',
                         'retrieval_beats': ['crypto_trader_en']},
    'crypto_btc_cycle_zh': {'id': 'crypto_btc_cycle_zh', 'lang': 'zh', 'name': '老周', 'beat': '比特币周期',
                            'retrieval_beats': ['crypto_macro_zh']},
    'btc_cycles_en': {'id': 'btc_cycles_en', 'lang': 'en', 'name': 'Elias', 'beat': 'Bitcoin cycles',
                      'retrieval_beats': ['crypto_macro_en']},
}
EV = {**CRASH, 'accounts': ['crypto_trader_zh', 'crypto_trader_zh2', 'crypto_macro_zh', 'crypto_btc_cycle_zh',
                            'crypto_macro_en', 'btc_cycles_en']}


def fake_window(subject, start, end):
    ts = int(datetime(2025, 10, 10, tzinfo=timezone.utc).timestamp())
    return [(ts, 112774.5)], 'Binance spot', {'url': 'u'}


def fake_latest(subject):
    ts = int(datetime(2026, 10, 11, tzinfo=timezone.utc).timestamp())
    return (ts, 83047.75), 'Binance spot', {'url': 'u2', 'fetched_at': '2026-10-11T11:41:00+00:00'}


DATA = {'window_fn': fake_window, 'latest_fn': fake_latest}


def test_calendar_shape_and_only_verified_used():
    evs = CAL['events']
    assert 60 <= len(evs) <= 120
    ids = [e['id'] for e in evs]
    assert len(ids) == len(set(ids))
    for e in evs:
        date.fromisoformat(e['date'])
        assert e['sources'] and e['accounts'] and e['verify']['url'] and e['title_en'] and e['title_zh']
    used = an.load_calendar()
    assert used and all(e['verify']['status'] == 'ok' for e in used)
    assert {'btc_whitepaper', 'btc_genesis_block', 'btc_pizza_day', 'the_merge', 'lehman', 'black_monday_1987',
            'spot_btc_etf_approval', 'ftx_bankruptcy', 'ust_depeg', 'crash_2025_10_10'} <= {e['id'] for e in used}
    assert {e['id']: e['date'] for e in used}['spot_btc_etf_approval'] == '2024-01-10'


def test_due_window_years_and_leap_day():
    evs = [CRASH, {**CRASH, 'id': 'leap', 'date': '2020-02-29'}, {**CRASH, 'id': 'wp', 'date': '2008-10-31'}]
    got = [(x['event']['id'], x['years'], x['offset_days']) for x in an.due('2026-10-11', evs, years=(1, 2, 5, 10))]
    assert got == [('crash_2025_10_10', 1, 1)]
    assert an.due('2026-10-13', evs, years=(1,), window=1) == []
    assert [x['years'] for x in an.due('2025-02-28', evs, years=(5,))] == [5]   # 29 Feb -> 28 Feb
    assert an.due('2028-10-31', evs, years=an.years_cfg({}))[0]['years'] == 20      # round-5 years on by default
    assert an.due('2028-10-31', evs, years=an.years_cfg({'FD_ANNIV_ROUND5': '0'})) == []


def test_choose_accounts_lang_balance_free_slot_and_dedupe():
    rows = [{'account_id': 'crypto_trader_zh', 'draft_status': 'draft_ready'},
            {'account_id': 'crypto_trader_zh', 'draft_status': 'draft_ready'}]       # trader_zh full
    chosen, skipped = an.choose_accounts(EV, ACCTS, rows)
    assert chosen == ['crypto_macro_zh', 'crypto_macro_en']                           # one zh + one en
    assert skipped['crypto_trader_zh'].startswith('no free slot')
    assert skipped['crypto_trader_zh2'] == 'not on roster'
    # already on the event today (zh + en) -> nobody else (event cap 2)
    taken = [{'account_id': 'crypto_btc_cycle_zh', 'post_kind': 'anniversary', 'draft_status': 'draft_ready',
              'anniversary': {'event_id': CRASH['id']}},
             {'account_id': 'crypto_macro_en', 'post_kind': 'anniversary', 'draft_status': 'draft_ready',
              'anniversary': {'event_id': CRASH['id']}}]
    chosen, skipped = an.choose_accounts(EV, ACCTS, taken)
    assert chosen == [] and skipped['crypto_macro_en'] == 'already has this event today'
    # per-language story cap 2 with a bigger event cap
    chosen, _ = an.choose_accounts(EV, ACCTS, [], per_event=5)
    assert sum(1 for a in chosen if ACCTS[a]['lang'] == 'zh') <= 2 and sum(1 for a in chosen if ACCTS[a]['lang'] == 'en') <= 2


def test_twins_never_both():
    accts = {'crypto_stable_yield_zh': {'id': 'crypto_stable_yield_zh', 'lang': 'zh', 'beat': '稳定币理财', 'lane_first': True,
                                        'retrieval_beats': ['crypto_stable_yield', 'crypto_defi']},
             'crypto_stable_yield_en': {'id': 'crypto_stable_yield_en', 'lang': 'en', 'beat': 'Stablecoin yield',
                                        'lane_first': True, 'retrieval_beats': ['crypto_stable_yield', 'crypto_defi']}}
    ev = {**CRASH, 'id': 'x', 'title_en': 'UST stablecoin loses its peg', 'title_zh': 'UST 稳定币脱锚',
          'accounts': list(accts)}
    chosen, skipped = an.choose_accounts(ev, accts, [])
    assert len(chosen) == 1 and 'twin' in skipped[[a for a in accts if a not in chosen][0]]


def test_pick_packet_has_dated_data_and_frame(tmp_path, monkeypatch):
    monkeypatch.setenv('FD_ANNIV_STORE', str(tmp_path))
    pk = an.pick('2026-10-11', accounts=ACCTS, events=[EV], base=tmp_path / 'inbox', data_fns=DATA)
    assert len(pk) == 1 and pk[0]['kind'] == 'anniversary' and pk[0]['years'] == 1 and pk[0]['offset_days'] == 1
    assert pk[0]['accounts'] == ['crypto_trader_zh', 'crypto_macro_en']
    assert pk[0]['data_lines'][0].startswith('THEN 2025-10-10: BTC daily close 112,774')
    assert pk[0]['data_lines'][-1].startswith('CHANGE: -26.4%')
    assert '一周年' in pk[0]['frame']['zh'] and 'anniversary' in pk[0]['frame']['en']
    assert json.loads((tmp_path / '2026-10-11.json').read_text())[0]['id'] == pk[0]['id']


def test_off_switch(monkeypatch):
    monkeypatch.setenv('FD_ANNIV', '0')
    assert an.pick('2026-10-11', accounts=ACCTS, events=[EV], write=False, base='/nonexistent/x') == []
    assert an.run('2026-10-11', write=False) == {'skipped': 'FD_ANNIV=0'}


GOOD_ZH = ('一年前的今天，币圈经历了有记录以来最大的一次清算\n\n2025年10月10日那天大饼收在112774附近。\n'
           '今天是83048，比当时低了26.4%')
GOOD_EN = ('One year ago today: the record liquidation day after the 100% China tariff threat.\n\n'
           'BTC closed at 112,774 on Oct 10, 2025. Today it sits near 83,000, down 26.4%.')


def _packet(base='/nonexistent/fd_anniv_test_inbox'):   # never the live inbox (it may hold today's anniversary rows)
    return an.pick('2026-10-11', accounts=ACCTS, events=[EV], write=False, data_fns=DATA, base=base)[0]


def test_check_frame_grounding_and_style():
    pk = _packet()
    assert an.check(GOOD_ZH, pk, ACCTS['crypto_macro_zh']) == []
    assert an.check(GOOD_EN, pk, ACCTS['crypto_macro_en']) == []
    codes = {f['code'] for f in an.check('2025年10月10日，250亿美元清算。大饼收在112774。', pk, ACCTS['crypto_macro_zh'])}
    assert 'stale_event_unframed' in codes            # old date, no look-back frame / today comparison
    assert 'anniv_ungrounded_number' in codes         # 250 is not in the packet
    codes = {f['code'] for f in an.check('A year ago BTC closed at 112,774. I bought the dip and made 57% since.', pk,
                                         ACCTS['crypto_macro_en'])}
    assert 'anniv_ungrounded_number' in codes and 'anniv_no_today' in codes
    assert stale_frame.ok(GOOD_ZH, day='2026-10-11', archive=True)


def test_compose_one_rewrites_then_holds():
    pk = _packet()
    calls = []

    def ask(messages):
        calls.append(messages)
        body = 'BTC 250亿美元清算。' if len(calls) == 1 else GOOD_ZH
        return {'body': body, 'why': 'w'}, {'response_model': 'gemini-test'}
    res = an.compose_one(ask, pk, ACCTS['crypto_macro_zh'])
    assert res['status'] == 'draft_ready' and res['attempts'] == 2 and res['hard'] == []
    assert '[hard_repair]' in calls[1][1]['content']
    sys_prompt = calls[0][0]['content']
    assert 'not X but Y' in sys_prompt and 'first-person' in sys_prompt and '一周年' in sys_prompt

    def bad(messages):
        return {'body': '250亿美元清算'}, {'response_model': 'gemini-test'}
    res = an.compose_one(bad, pk, ACCTS['crypto_macro_zh'])
    assert res['status'] == 'needs_review' and 'anniv_ungrounded_number' in res['hard']


def test_run_writes_inbox_rows(tmp_path, monkeypatch):
    monkeypatch.setenv('FD_ANNIV_STORE', str(tmp_path / 'store'))
    monkeypatch.setattr(an, 'roster', lambda: ACCTS)
    monkeypatch.setattr(an, 'load_calendar', lambda *a, **k: [EV])
    monkeypatch.setattr(an, 'then_vs_now', lambda ev, **k: an.__dict__['_tvn'](ev))
    an._tvn = lambda ev: _real_tvn(ev, window_fn=fake_window, latest_fn=fake_latest)

    def ask(messages):
        lang = json.loads(messages[1]['content'])['account']['lang']
        return {'body': GOOD_ZH if lang == 'zh' else GOOD_EN, 'why': 'w'}, {'response_model': 'gemini-test'}
    out = an.run('2026-10-11', base=tmp_path / 'inbox', ask=ask, log=lambda *_: None)
    assert [d['status'] for d in out['drafts']] == ['draft_ready', 'draft_ready']
    rows = [json.loads(p.read_text()) for p in sorted((tmp_path / 'inbox' / '2026-10-11').glob('*.json'))]
    assert {r['post_kind'] for r in rows} == {'anniversary'} and {r['label'] for r in rows} == {'周年'}
    assert all(r['support_citations'] and r['anniversary']['event_id'] == CRASH['id'] for r in rows)
    assert all(r['publishable'] is False and r['suggested_post_time_london'] for r in rows)
    # a second run the same day adds nothing (accounts already on the event, event cap reached)
    out2 = an.run('2026-10-11', base=tmp_path / 'inbox', ask=ask, log=lambda *_: None)
    assert out2['drafts'] == []


_real_tvn = an.then_vs_now


def test_verifier_spellings_and_near_match():
    import verify_event_calendar as v
    d = date(2022, 9, 15)
    assert 'September 15, 2022' in v.spellings(d) and '15 September 2022' in v.spellings(d)
    assert v.near_match('in 2022 the network ... on september 15 it moved to proof of stake', d)
    assert v.near_match('on september 15 it moved', d) is None
    ev = {'id': 'x', 'date': '2022-09-15', 'sources': [], 'verify': {'url': 'u'}}
    assert v.check(ev, fetch_fn=lambda u: 'On 15 September 2022, Ethereum transitioned')['status'] == 'ok'
    assert v.check(ev, fetch_fn=lambda u: 'Retrieved nothing here 2021')['status'] == 'date_not_found'
