"""Oct 8 archive rollout: claim fidelity (draft 3 fix), 20-account flags, daily caps, cache-by-month material and the
常青 evergreen variant. All texts here are synthetic (no donor / raw post text in git)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from live import archive_evergreen as ae, archive_lookback as al, compose_inbox  # noqa: E402
from tests.test_archive_lookback import CFG, EN, GOOD, ZH, FakeClient, _cand, _post  # noqa: E402

LONG = {'id': 'zh_longterm_investing', 'no': 10, 'name': '慢慢小鹿', 'beat': '长期投资 · 组合与复利', 'lang': 'zh',
        'kind': 'macro', 'retrieval_beats': ['macro_zh']}
EVG_CFG = {**CFG, 'evergreen': {'min_chars': {'zh': 60, 'en': 200}, 'min_rule_score': 1.0, 'per_handle': 2,
                                'classify_top_k': 10, 'max_candidates_to_model': 3, 'dup_similarity': 0.3,
                                'verbatim_zh_chars': 10, 'verbatim_en_words': 7}}

# synthetic stand-in for the draft-3 source: a diary-style quote post about a yield vault
DIARY = ('早上又弄了点钱买了BTC，存进收益金库，最近签到都有点倦怠了。BTC 生态的收益产品还在往前走，'
         '喜欢折腾的可以研究一下。')
CARD_REC = {'speaker': '@kiki520_eth', 'date': '2025-02-25', 'claim': '130 一线有人接', 'claim_type': 'recommendation',
            'condition': '', 'about_subject': True, 'data_tests_claim': 'tests_claim', 'quotable': '130 一线有人接'}


# ---------------------------------------------------------------- draft 3 regression: candidate filter

def test_quote_posts_and_diary_posts_are_not_lookback_candidates():
    assert al.eligible(_post(text=DIARY, quote=True), LONG, CFG)[1] == 'quote post (context missing)'
    assert al.eligible(_post(text=DIARY), LONG, CFG)[1] == 'personal diary'
    assert al.eligible(_post(), ZH, CFG)[0]                       # the ordinary SOL call still passes


# ---------------------------------------------------------------- claim cards and deterministic claim checks

def test_claim_type_prediction_framing_is_hard():
    c = {**_cand(), 'claim': CARD_REC}
    body = GOOD.replace('写过', '预测')
    codes = {f['code'] for f in al.check(body, c, ZH)[0] if f['level'] == 'hard'}
    assert 'archive_claim_type' in codes
    assert 'archive_claim_type' not in {f['code'] for f in al.check(GOOD, c, ZH)[0]}
    pred = {**c, 'claim': {**CARD_REC, 'claim_type': 'prediction'}}
    assert 'archive_claim_type' not in {f['code'] for f in al.check(body, pred, ZH)[0]}


def test_conditional_needs_its_condition_and_metric_must_test_claim():
    cond = {**_cand(), 'claim': {**CARD_REC, 'claim_type': 'conditional', 'condition': '如果解锁前没跌破'}}
    assert 'archive_condition_dropped' in {f['code'] for f in al.check(GOOD, cond, ZH)[0]}
    kept = GOOD.replace('写过', '写过：如果解锁前没跌破，')
    assert 'archive_condition_dropped' not in {f['code'] for f in al.check(kept, cond, ZH)[0]}
    ctx = {**_cand(), 'claim': {**CARD_REC, 'data_tests_claim': 'context_only'}}
    assert 'archive_metric_untested' in {f['code'] for f in al.check(GOOD, ctx, ZH)[0] if f['level'] == 'hard'}


@pytest.mark.parametrize('card,ok', [
    (None, False), ({**CARD_REC, 'claim_type': 'personal_update'}, False), ({**CARD_REC, 'about_subject': False}, False),
    ({**CARD_REC, 'data_tests_claim': 'unrelated'}, False), (CARD_REC, True)])
def test_usable_claim(card, ok):
    assert al.usable_claim(card)[0] is ok


def test_claim_cards_parse_and_drop_unverbatim_quotable():
    c = _cand()

    def ask(messages):
        assert 'claim_type' in messages[0]['content']
        return {'items': [{**CARD_REC, 'id': c['id'], 'quotable': '一定守得住', 'claim_type': 'weird'}]}
    cards = al.claim_cards(ask, [c])
    assert cards[c['id']]['quotable'] == '' and cards[c['id']]['claim_type'] == 'opinion'


def test_judge_findings_hard_on_issue_or_error():
    c = {**_cand(), 'claim': CARD_REC}
    assert al.judge_findings(lambda m: {'faithful': True, 'issues': []}, GOOD, c) == []
    f = al.judge_findings(lambda m: {'faithful': False, 'issues': [{'type': 'misattributed_view', 'detail': 'x'}]},
                          GOOD, c)
    assert f[0]['code'] == 'archive_misrepresents' and f[0]['level'] == 'hard'

    def boom(m):
        raise RuntimeError('relay down')
    assert al.judge_findings(boom, GOOD, c)[0]['code'] == 'archive_fidelity_unchecked'


def test_compose_judge_misrepresentation_rewrite_then_hold():
    c = {**_cand(), 'claim': CARD_REC}
    verdicts = iter([[{'code': 'archive_misrepresents', 'level': 'hard', 'detail': ['misattributed_view: x']}], []])
    r = al.compose(FakeClient([GOOD, GOOD]), ZH, [c], '2026-10-08', judge=lambda b, cand: next(verdicts))
    assert r['status'] == 'draft_ready' and r['hard_repair']['first_codes'] == ['archive_misrepresents']
    bad = [{'code': 'archive_misrepresents', 'level': 'hard', 'detail': ['x']}]
    r = al.compose(FakeClient([GOOD, GOOD]), ZH, [c], '2026-10-08', judge=lambda b, cand: list(bad))
    assert r['status'] == 'needs_review' and r['hard'] == ['archive_misrepresents']


def test_handle_is_not_unexplained_jargon():
    c = {**_cand(), 'handle': 'YaelC_03'}
    body = GOOD.replace('@kiki520_eth', '@YaelC_03')
    assert 'jargon_unexplained' not in {f['code'] for f in al.check(body, c, ZH)[0]}


def test_recheck_without_model_keeps_the_stored_judge_verdict(tmp_path, monkeypatch):
    raw = tmp_path / 'raw'
    monkeypatch.setenv('FD_ARCHIVE_RAW', str(raw))
    from tests.test_archive_lookback import SOL_TEXT
    page = {'result': {'timeline': {'instructions': [{'entries': [{'content': {'itemContent': {'tweet_results': {'result': {
        'rest_id': '1894', 'legacy': {'full_text': SOL_TEXT, 'user_id_str': '9', 'created_at': 'Tue Feb 25 10:00:00 +0000 2025',
                                      'lang': 'zh'}}}}}}]}]}}}
    (raw / 'raw' / 'kiki520_eth').mkdir(parents=True)
    (raw / 'raw' / 'kiki520_eth' / 'feb2025.json').write_text(json.dumps(page))
    r = al.compose(FakeClient([GOOD]), ZH, [{**_cand(), 'claim': CARD_REC}], '2026-10-08')
    row = al.inbox_row(r, ZH, '2026-10-08', 'arc20261008T000000', post_time='2026-10-08T09:30:00+01:00')
    assert row['archive']['claim'] == CARD_REC and row['archive']['variant'] == 'then_vs_now'
    row['findings'].append({'code': 'archive_misrepresents', 'level': 'hard', 'detail': ['x']})
    base = tmp_path / 'inbox'
    compose_inbox.add({**row, 'held': True, 'hold_reason': 'hard: archive_misrepresents', 'draft_status': 'needs_review'},
                      base=base)
    accts = tmp_path / 'accounts.json'
    accts.write_text(json.dumps({'accounts': [ZH]}))
    out = al.recheck('2026-10-08', base=base, accounts_path=accts, log=lambda *_: None)
    assert out[0]['hard'] == ['archive_misrepresents']
    out = al.recheck('2026-10-08', base=base, accounts_path=accts, log=lambda *_: None,
                     ask=lambda m: {'faithful': True, 'issues': []})
    assert out[0]['hard'] == []


# ---------------------------------------------------------------- rollout flags, gate, caps

def test_enabled_all_and_narrowing_flags(monkeypatch):
    shipped = al.load_config()
    assert shipped['enabled_accounts'] == 'all' and shipped['per_day'] == 1
    monkeypatch.delenv('FD_ACCOUNTS_EXTRA', raising=False)
    monkeypatch.delenv('FD_ACCOUNTS_NEW', raising=False)
    ids = al.enabled_accounts(shipped, {})   # Oct 8: 20 mains + 6 spares + 10 new (live/fd_accounts.py)
    assert len(ids) == 36 and 'single_stock_deepdive_en' in ids and 'crypto_meme_zh' in ids
    monkeypatch.setenv('FD_ACCOUNTS_EXTRA', '0')
    monkeypatch.setenv('FD_ACCOUNTS_NEW', '0')
    assert len(al.enabled_accounts(shipped, {})) == 20
    assert al.enabled_accounts(shipped, {'FD_ARCHIVE': '0'}) == []
    assert al.enabled_accounts(shipped, {'FD_ARCHIVE_ACCOUNTS': 'crypto_macro_en,zh_us_stocks'}) == \
        ['zh_us_stocks', 'crypto_macro_en']
    assert al.variants_enabled(shipped, {}) == ['then_vs_now', 'evergreen']
    assert al.variants_enabled(shipped, {'FD_ARCHIVE_EVERGREEN': '0'}) == ['then_vs_now']
    assert al.variants_enabled(shipped, {'FD_ARCHIVE_THEN_NOW': '0'}) == ['evergreen']
    assert shipped['rapid_max_calls_per_day'] <= 40 and shipped['model_usd_per_day'] <= 1.0


def test_gate_fill_and_slow_day_second_post(tmp_path, monkeypatch):
    monkeypatch.setenv('FD_SLOT_RULE', '0')   # pre-Oct 9 gap rule; the slot rule: tests/test_slot_rule_oct9.py
    monkeypatch.delenv('FD_ARCHIVE', raising=False)
    monkeypatch.delenv('FD_ARCHIVE_ACCOUNTS', raising=False)
    cfg = {**CFG, 'slow_day_fresh_min': 2}
    base = tmp_path / 'inbox'

    def add(i, published):
        compose_inbox.add({'id': f'c-{i}', 'day': '2026-10-09', 'account_id': 'crypto_altcoin_zh', 'text': 'x',
                           'draft_status': 'draft_ready', 'source': {'published_at': published}}, base=base)
    add(1, '2026-10-09T01:00:00+00:00')
    ok, why = al.gate('crypto_altcoin_zh', '2026-10-09', config=cfg, base=base)
    assert ok and why.startswith('gap')                                       # 1 ready < 2: fill
    add(2, '2026-09-20T01:00:00+00:00')                                         # stale source
    ok, why = al.gate('crypto_altcoin_zh', '2026-10-09', config=cfg, base=base)
    assert ok and why.startswith('slow day')                                  # 2 ready, 1 fresh: 2nd post
    add(3, '2026-10-08T20:00:00+00:00')
    ok, why = al.gate('crypto_altcoin_zh', '2026-10-09', config=cfg, base=base)
    assert not ok                                                               # 3 ready, 2 fresh
    assert not al.gate('crypto_altcoin_zh', '2026-10-09', config=CFG, base=base)[0]   # slow-day rule off


def test_day_caps_count_all_runs(tmp_path, monkeypatch):
    monkeypatch.setenv('FD_ARCHIVE_STORE', str(tmp_path))
    cfg = {'rapid_max_calls_per_day': 40, 'rapid_max_calls': 120, 'model_usd_per_day': 1.0, 'compose_budget_usd': 2.0}
    assert al.run_caps(cfg, '2026-10-09') == (40, 1.0)
    for i in range(35):
        al._jsonl(tmp_path / 'fetch_log.jsonl', {'at': '2026-10-08T17:00:00+00:00', 'status': 200})   # 01:00 Beijing 10-09
    al._jsonl(tmp_path / 'fetch_log.jsonl', {'at': '2026-10-08T15:00:00+00:00', 'status': 200})       # 23:00 Beijing 10-08
    al._jsonl(tmp_path / 'fetch_log.jsonl', {'at': 'x', 'day': '2026-10-09'})
    assert al.calls_on('2026-10-09') == 36
    al.record_spend('2026-10-09', 'a', 0.7, 'evergreen')
    al.record_spend('2026-10-08', 'a', 5.0, 'evergreen')
    assert al.run_caps(cfg, '2026-10-09') == (4, 0.3)
    assert al.run_caps(cfg, '2026-10-09', rapid_cap=2, budget_usd=0.1) == (2, 0.1)
    al.record_spend('2026-10-09', 'b', 0.4, 'then_vs_now')
    assert al.run_caps(cfg, '2026-10-09')[1] == 0.0


def test_search_client_cap_and_day_in_log(tmp_path, monkeypatch):
    c = al.SearchClient('k', 1, tmp_path / 'log.jsonl', day='2026-10-09')

    class R:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{}'
    monkeypatch.setattr(al.urllib.request, 'urlopen', lambda req, timeout: R())
    c.search('from:a', account='x', handle='a', window='top_2025-09', search_type='Top')
    with pytest.raises(RuntimeError):
        c.search('from:a', account='x', handle='a', window='top_2025-09')
    row = al._read_jsonl(tmp_path / 'log.jsonl')[0]
    assert row['day'] == '2026-10-09' and row['type'] == 'Top' and 'k' not in json.dumps(row)


def _page(pid, text, created, likes=10, rts=1, bm=2):
    return {'result': {'timeline': {'instructions': [{'entries': [{'content': {'itemContent': {'tweet_results': {
        'result': {'rest_id': pid, 'legacy': {'full_text': text, 'user_id_str': '9', 'created_at': created, 'lang': 'zh',
                                              'favorite_count': likes, 'retweet_count': rts, 'bookmark_count': bm}}}}}}]}]}}}


def test_gather_cache_by_handle_month_allowance_and_local(tmp_path, monkeypatch):
    monkeypatch.setenv('FD_ARCHIVE_RAW', str(tmp_path / 'raw'))
    monkeypatch.setenv('FD_DONOR_POSTS', str(tmp_path / 'donors'))
    (tmp_path / 'donors').mkdir()
    (tmp_path / 'donors' / 'a.jsonl').write_text(json.dumps(
        {'id': '7', 'created': 'Mon Sep 15 10:00:00 +0000 2025', 'text': 'local', 'likes': 3, 'views': 100}) + '\n')
    cfg = {'months': ['2025-02', '2025-09']}

    class Client:
        made = 0

        def search(self, query, **kw):
            self.made += 1
            assert kw['search_type'] == 'Top' and 'since:' in query
            return _page(str(100 + self.made), 'top post', 'Tue Feb 25 10:00:00 +0000 2025')
    cl = Client()
    posts, calls = al.gather('acct', [('a', 'donor'), ('b', 'x_source_core')], '2026-10-09', config=cfg, client=cl,
                             allowance=3)
    assert calls == 3 and cl.made == 3                     # allowance bounds the calls
    assert {p['id'] for p in posts} >= {'7', '101'}
    assert al.months_for(cfg, '2026-10-09')[0] == '2025-10' and '2025-02' in al.months_for(cfg, '2026-10-09')
    posts2, calls2 = al.gather('other', [('a', 'donor'), ('b', 'x_source_core')], '2026-10-09', config=cfg,
                               client=cl, allowance=0)
    assert calls2 == 0 and {p['id'] for p in posts2} == {p['id'] for p in posts}   # cache shared, no new call
    top = next(p for p in posts if p['id'] == '101')
    assert top['retweets'] == 1 and top['bookmarks'] == 2 and top['engagement'] == 10 + 2 + 4


def test_variant_order_alternates():
    a = al.variant_order('x', '2026-10-09', ['then_vs_now', 'evergreen'], ['x', 'y'])
    b = al.variant_order('y', '2026-10-09', ['then_vs_now', 'evergreen'], ['x', 'y'])
    assert sorted(a) == sorted(b) and a != b
    assert al.variant_order('x', '2026-10-09', ['evergreen'], ['x']) == ['evergreen']


# ---------------------------------------------------------------- evergreen variant

LESSON = ('很多人亏钱不是因为看错，而是因为仓位失控。我的三条规则：第一，单笔仓位不超过 5%；第二，止损在下单前就写好；'
          '第三，连续亏三次就停手一天。长期活下来比短期赚得多重要，纪律就是复利的前提。')
NEWS = '今天晚上 8 点开奖，转发抽 10 人，每人 100U，关注 @xx 即可参与。今天行情很猛，大家冲。' * 2


def _ep(pid, text, handle='lark', likes=50, **kw):
    return {**_post(pid, text=text, handle=handle), 'likes': likes, 'retweets': 5, 'bookmarks': 20,
            'engagement': likes + 50, **kw}


def test_evergreen_rules():
    assert ae.eligible(_ep('1', LESSON), LONG, EVG_CFG)[0]
    assert ae.eligible(_ep('2', NEWS), LONG, EVG_CFG)[1] in ('promo', 'short') or not ae.eligible(_ep('2', NEWS), LONG, EVG_CFG)[0]
    assert ae.eligible(_ep('3', LESSON, quote=True), LONG, EVG_CFG)[1] == 'not an original'
    assert ae.eligible(_ep('4', 'Position sizing is the whole game. ' * 12), LONG, EVG_CFG)[1] == 'other language'
    assert ae.evergreen_score(LESSON) > ae.evergreen_score('今天下午 3 点开盘，刚刚拉了一波，今晚继续看。' * 3)


def test_evergreen_candidates_dedupe_used_taken_history_and_rank():
    posts = [_ep('1', LESSON, likes=10), _ep('2', LESSON.replace('5%', '3%'), handle='b', likes=900),
             _ep('3', LESSON.replace('三条', '几条'), handle='c', likes=20)]
    got = ae.candidates(posts, LONG, '2026-10-09', config=EVG_CFG)
    assert got[0]['id'] == '2'                                   # engagement ranks first
    got = ae.candidates(posts, LONG, '2026-10-09', config=EVG_CFG, used={'x:2'}, taken={'x:3'})
    assert [c['id'] for c in got] == ['1']
    assert ae.candidates(posts, LONG, '2026-10-09', config=EVG_CFG, past=[LESSON]) == []   # 30-day near-duplicate


def test_verbatim_runs_zh_en():
    assert ae.verbatim_runs('我觉得止损在下单前就写好；第三，连续亏三次最要紧', LESSON)       # 10+ identical characters
    assert not ae.verbatim_runs('下单之前先定好止损位置', LESSON)
    src = 'the best traders size every position so that one mistake can never knock them out of the game'
    assert ae.verbatim_runs('Size so that one mistake can never knock them out of the game.', src)
    assert not ae.verbatim_runs('One bad trade should never end your career; size for that.', src)


EVG_GOOD = ('亏钱的人，多数不是判断错了，是仓位先失了控。\n\n给自己定几条硬规矩：单笔不超过 5%，下单前先写好止损，'
            '连着错三回就歇一天。\n\n能长期留在场上，比某一次赚得多更值钱。纪律守住了，复利才有机会发生。')


def _evg_cand():
    c, _ = ae.eligible(_ep('1', LESSON), LONG, EVG_CFG)
    return {**c, 'verdict': {'evergreen': True, 'still_true': True, 'kind': 'checklist', 'fit': 3,
                             'core_idea': '仓位纪律比判断对错更决定长期结果', 'stale_bits': []}}


def test_evergreen_check_good_and_hard_codes():
    c = _evg_cand()
    assert not [f for f in ae.check(EVG_GOOD, c, LONG, config=EVG_CFG) if f['level'] == 'hard']
    cases = {
        'evergreen_verbatim': EVG_GOOD + '止损在下单前就写好；第三，连续亏三次就停手。',
        'evergreen_number': EVG_GOOD.replace('5%', '8%'),
        'evergreen_dated': EVG_GOOD.replace('能长期', '今天能长期'),
    }
    for code, body in cases.items():
        assert code in {f['code'] for f in ae.check(body, c, LONG, config=EVG_CFG) if f['level'] == 'hard'}, code
    priced = {**c, 'text': c['text'] + ' 比特币 9 万美元时也一样。'}
    assert 'evergreen_number' in {f['code'] for f in ae.check(EVG_GOOD + '比特币 9 万美元时也一样。', priced, LONG,
                                                             config=EVG_CFG)}
    assert 'evergreen_dated' in {f['code'] for f in ae.check('一年前有人说过：' + EVG_GOOD, c, LONG, config=EVG_CFG)}
    assert 'evergreen_dup_history' in {f['code'] for f in ae.check(EVG_GOOD, c, LONG, past=[EVG_GOOD], config=EVG_CFG)}


class EvgClient:
    def __init__(self, bodies):
        self.bodies, self.messages = list(bodies), []

    def __call__(self, stage, messages, max_tokens):
        assert stage == 'compose'
        self.messages.append(messages)
        return {'text': json.dumps({'pick': '1', 'body': self.bodies.pop(0), 'why': 'w'}),
                'response_model': 'gemini-3.1-pro-preview'}


def test_evergreen_compose_rewrite_judge_and_row():
    c = _evg_cand()
    copied = EVG_GOOD + '止损在下单前就写好；第三，连续亏三次就停手。'
    r = ae.compose(EvgClient([copied, EVG_GOOD]), LONG, [c], '2026-10-09', judge=lambda b, cand: [], config=EVG_CFG)
    assert r['status'] == 'draft_ready' and r['hard_repair']['first_codes'] == ['evergreen_verbatim']
    r2 = ae.compose(EvgClient([EVG_GOOD, EVG_GOOD]), LONG, [c], '2026-10-09', config=EVG_CFG,
                    judge=lambda b, cand: [{'code': 'evergreen_misrepresents', 'level': 'hard', 'detail': ['x']}])
    assert r2['status'] == 'needs_review' and r2['hard'] == ['evergreen_misrepresents']
    row = ae.inbox_row(r, {**LONG, 'no': 10}, '2026-10-09', 'arc20261009T000000', post_time='2026-10-09T09:00:00+01:00')
    assert row['post_kind'] == al.POST_KIND and row['label'] == '常青' and row['archive']['variant'] == 'evergreen'
    assert row['archive']['event_keys'] == ['x:1'] and row['archive']['engagement']['likes'] == 50
    assert row['publishable'] is False and '@' not in row['text']


def test_evergreen_classify_keeps_only_evergreen_still_true_fitting():
    cands = [{**_ep(str(i), LESSON), 'date': '2025-09-01'} for i in range(3)]
    out = {'items': [{'id': '0', 'evergreen': True, 'still_true': True, 'fit': 2},
                     {'id': '1', 'evergreen': True, 'still_true': False, 'fit': 3},
                     {'id': '2', 'evergreen': True, 'still_true': True, 'fit': 0}]}
    v = ae.classify(lambda m: out, cands, LONG, '2026-10-09')
    assert [k for k in v if ae.keep(v[k])] == ['0']


def test_dashboards_tag_evergreen():
    import build_ops_dashboard as ops
    m = ops.media_of({'post_kind': al.POST_KIND, 'archive': {'variant': 'evergreen', 'original_url': 'u'}})
    assert m['archive'] is True and m['archive_variant'] == 'evergreen'
    from backend.compose_inbox import render
    html = render([{'id': 'e', 'day': '2026-10-09', 'account_id': 'a', 'text': 't', 'post_kind': al.POST_KIND,
                    'archive': {'variant': 'evergreen'}}], '2026-10-09')
    assert '【常青】' in html


def test_refused_calls_are_not_spend_and_quota_errors_stop(tmp_path):
    ok, refused = tmp_path / 'a.json', tmp_path / 'b.json'
    ok.write_text(json.dumps({'usage': {'input_tokens': 1}, 'estimated_cost_usd': 0.04}))
    refused.write_text(json.dumps({'error': 'Relay HTTP 403 额度不足', 'estimated_cost_usd': 0.23}))

    class C:
        calls = [{'path': str(ok)}, {'path': str(refused)}]
    assert al._cost(C()) == 0.04
    from live.writer_backend import ProviderQuotaError
    assert al._quota_error(ProviderQuotaError('x'))
    assert al._quota_error(RuntimeError("Relay HTTP 403: {'code': 'insufficient_user_quota'}"))
    assert not al._quota_error(RuntimeError('ReadTimeout'))


def test_evergreen_rules_drop_own_book_diary():
    assert ae.eligible(_ep('9', '醒了，' + LESSON), LONG, EVG_CFG)[1] == 'personal diary'
    assert ae.eligible(_ep('9', LESSON.replace('很多人', '我自己有约 1000 ETH 在做，很多人')), LONG, EVG_CFG)[1] == 'personal diary'
