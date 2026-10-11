"""Oct 11 account audit fixes: story dedupe, lane allowlist, post-kind mix, diary slot, invented-bio check."""
import json
from datetime import date

import pytest

from live import lane_allow, post_kind, story_dedupe as sd, story_label as sl

# live/personas/posting_habits/account_mix.json is local only (donor-derived; scripts/build_account_mix.py)
needs_mix = pytest.mark.skipif(not lane_allow.PATH.exists(), reason='local account_mix.json not built')


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv('FD_STORY_STORE', str(tmp_path / 'labels'))
    sl._CACHE.clear()
    sl._LOADED.clear()
    for k in ('FD_STORY_DEDUPE', 'FD_LANE_ALLOW', 'FD_POST_KIND', 'FD_DIARY_SLOT', 'FD_STORY_PER_LANG_DAY',
              'FD_STORY_72H', 'FD_PERSONA_LIFE', 'FD_TWIN_RULE'):
        monkeypatch.delenv(k, raising=False)


def lab(e, a, o='', k='', b='stablecoins_tether'):
    return {'b': b, 'e': e, 'a': a, 'o': o, 'k': k}


D = date(2026, 10, 12)


def st(e, a, o='', k=''):
    return sd.story_of('x', label=lab(e, a, o, k))


# ---------------------------------------------------------------- story keys
def test_same_event_same_key_any_wording():
    a = st('Tether', 'freezes', k='Tether freezes USDT wallets')
    b = st('tether', 'freezes', k='Tether freezes accounts')
    assert sd.same_story(a, b)


def test_pairing_key_matches_regardless_of_order():
    a = st('Polygon', 'integrates', 'TRON', 'USDT moves from TRON to Polygon')
    b = st('TRX', 'integrates', 'Polygon', 'Tron Polygon USDT bridge')
    assert sd.same_story(a, b)


def test_generic_entity_price_moves_are_not_one_story():
    a = st('Bitcoin', 'price_move', k='Bitcoin drops below 80k')
    b = st('BTC', 'price_move', k='BTC weekly close')
    assert not sd.same_story(a, b)


def test_shared_verbs_do_not_merge_stories():
    assert not sd.same_story(st('Robinhood', 'buys', 'BTC', 'Robinhood buys BTC'),
                             st('Strategy', 'buys', 'BTC', 'Strategy buys more BTC'))
    assert sd.same_story(st('X', 'other', k='Tether freezes Conduit wallets'), st('Y', 'other', k='Conduit wallets frozen by Tether'))


def test_different_entities_not_merged():
    assert not sd.same_story(st('Robinhood', 'buys', 'BTC', 'Robinhood buys BTC'),
                             st('Tether', 'freezes', k='Tether freezes wallets'))


# ---------------------------------------------------------------- caps
def test_cap_two_accounts_per_language_per_day():
    led = sd.Ledger(D)
    s = st('Tether', 'freezes')
    led.add('crypto_macro_zh', 'zh', s)
    assert led.check('crypto_diary_zh', 'zh', s) is None
    led.add('crypto_diary_zh', 'zh', s)
    assert led.check('crypto_newbie_zh', 'zh', s).startswith('story_cap_lang_day')
    assert led.check('crypto_macro_en', 'en', s) is None   # other language still free


def test_cap_four_accounts_in_72h_network_wide():
    led = sd.Ledger(D)
    s = st('Robinhood', 'buys', 'BTC')
    led.add('a1', 'zh', s, day=date(2026, 10, 10))
    led.add('a2', 'en', s, day=date(2026, 10, 10))
    led.add('a3', 'zh', s, day=date(2026, 10, 11))
    led.add('a4', 'en', s, day=date(2026, 10, 11))
    assert led.check('a5', 'en', s).startswith('story_cap_72h')
    old = sd.Ledger(D, [dict(x, day=date(2026, 10, 8)) for x in led.items])
    assert old.check('a5', 'en', s) is None   # older than the 3-day window


def test_twins_never_share_a_story_same_day():
    led = sd.Ledger(D)
    s = st('pump.fun', 'launches')
    led.add('crypto_meme_zh', 'zh', s)
    assert led.check('crypto_meme_en', 'en', s).startswith('story_twin')
    led2 = sd.Ledger(D)
    led2.add('crypto_meme_zh', 'zh', s, day=date(2026, 10, 11))
    assert led2.check('crypto_meme_en', 'en', s) is None


def test_kill_switch(monkeypatch):
    monkeypatch.setenv('FD_STORY_DEDUPE', '0')
    led = sd.Ledger(D)
    s = st('Tether', 'freezes')
    for a in ('x1', 'x2', 'x3'):
        led.add(a, 'zh', s)
    assert led.check('x4', 'zh', s) is None
    assert not led.repeat('x1', s)


def test_seven_day_memory():
    led = sd.Ledger(D)
    s = st('SUI', 'price_move', k='SUI breaks resistance')
    led.add('crypto_trader_en', 'en', s, day=date(2026, 10, 7))
    assert led.repeat('crypto_trader_en', s)
    assert not led.repeat('crypto_trader_en', st('Hyperliquid', 'launches'))
    led2 = sd.Ledger(D)
    led2.add('crypto_trader_en', 'en', s, day=date(2026, 10, 4))
    assert not led2.repeat('crypto_trader_en', s)


def test_ledger_from_inbox_uses_stored_story(tmp_path, monkeypatch):
    base = tmp_path / 'inbox'
    (base / '2026-10-11').mkdir(parents=True)
    row = {'id': 'r1', 'account_id': 'crypto_macro_zh', 'lang': 'zh', 'day': '2026-10-11', 'text': 'x', 'body': 'x',
           'draft_status': 'draft_ready', 'held': False, 'story': {'keys': ['ea:tether|freezes'], 'tokens': []}}
    (base / '2026-10-11' / 'r1.json').write_text(json.dumps(row))
    held = dict(row, id='r2', held=True)
    (base / '2026-10-11' / 'r2.json').write_text(json.dumps(held))
    monkeypatch.setenv('FD_COMPOSE_INBOX', str(base))
    led = sd.ledger_for(D)
    assert len(led.items) == 1
    assert led.repeat('crypto_macro_zh', st('Tether', 'freezes'))


# ---------------------------------------------------------------- labels
def test_label_many_caches_and_cleans(tmp_path):
    calls = []

    def caller(items):
        calls.append(len(items))
        return {h: {'b': 'stablecoins_tether', 'e': 'Tether', 'a': 'FREEZES', 'o': '', 'k': 'Tether freezes'}
                for h, _t in items}
    labs, stats = sl.label_many(['Tether froze 3 wallets', 'Tether froze 3 wallets', 'other'], caller=caller)
    assert stats['labelled'] == 2 and calls == [2]
    assert all(v['a'] == 'freezes' for v in labs.values())
    sl._CACHE.clear(); sl._LOADED.clear()
    labs2, stats2 = sl.label_many(['Tether froze 3 wallets'], caller=caller)
    assert stats2['cached'] == 1 and calls == [2]


def test_label_failure_is_not_fatal():
    def boom(items):
        raise RuntimeError('down')
    labs, stats = sl.label_many(['a text'], caller=boom)
    assert labs == {} and stats['errors'] == 1


def test_no_model_no_call():
    labs, stats = sl.label_many(['a text'], allow_model=False)
    assert labs == {} and stats['labelled'] == 0


def test_keyword_bucket():
    assert sl.keyword_bucket('Polymarket odds on the election') == 'prediction_markets'
    assert sl.keyword_bucket('Tether freezes USDT') == 'stablecoins_tether'
    assert sl.keyword_bucket('hello world') is None


# ---------------------------------------------------------------- lane allowlist
@needs_mix
def test_lane_verdicts():
    assert lane_allow.verdict('crypto_meme_en', 'memecoins_launchpads') == 'on'
    assert lane_allow.verdict('crypto_meme_en', 'stablecoins_tether') == 'off'
    assert lane_allow.verdict('crypto_thesis_en', 'ai_tech') == 'offlane_ok'
    assert lane_allow.verdict('crypto_meme_en', None) is None
    assert lane_allow.verdict('crypto_meme_en', 'personal_life') is None


@needs_mix
def test_lane_kill_switch(monkeypatch):
    monkeypatch.setenv('FD_LANE_ALLOW', '0')
    assert lane_allow.verdict('crypto_meme_en', 'stablecoins_tether') is None


@needs_mix
def test_quota_is_1_to_3_and_fit_accounts():
    for aid, c in lane_allow.mix().items():
        assert 1 <= lane_allow.quota(aid) <= 3
        assert c['allow'], aid
    fit = lane_allow.fit_accounts('stablecoins_tether', 'zh')
    assert 'crypto_stable_yield_zh' in fit
    assert lane_allow.fit_accounts('trading_psychology_method', 'en') == []   # a style bucket is never handed over
    assert all(lane_allow.cfg(a)['lang'] == 'zh' for a in fit)


def test_offlane_used_counts_tagged_rows():
    rows = [{'account_id': 'a', 'offlane_aside': True}, {'account_id': 'a'}, {'account_id': 'b', 'offlane_aside': True}]
    assert lane_allow.offlane_used('a', rows) == 1


@needs_mix
def test_account_mix_has_no_text():
    raw = lane_allow.PATH.read_text()
    data = json.loads(raw)
    for c in data['accounts'].values():
        assert set(c) <= {'lang', 'core', 'allow', 'offlane_ok', 'donor_bucket_share', 'weekly_14', 'offlane_per_week',
                          'diary_slot', 'meme_lane', 'persona_life_details'}
        assert c['persona_life_details'] == []   # PENDING Fiona's approval


# ---------------------------------------------------------------- post kinds
@needs_mix
def test_needs_human_floor_cap_and_spread():
    from datetime import timedelta
    assert post_kind.needs_human('crypto_diary_zh', {'c': 5})          # < 2 human posts this week (no spreading)
    assert not post_kind.needs_human('single_stock_deepdive_en', {'a': 3, 'b': 2, 'reaction': 2, 'question': 1})
    # spread over the week: exactly human_per_week() of 7 days are human days
    days = [date(2026, 10, 12) + timedelta(days=i) for i in range(7)]
    for aid in ('crypto_diary_zh', 'single_stock_deepdive_en', 'crypto_meme_en'):
        hits = sum(post_kind.needs_human(aid, {'c': 5}, day=d) for d in days)
        assert hits == post_kind.human_per_week(aid)
        assert 2 <= hits <= 4
    # the weekly human count keeps a+b+c within the donor share + 15pp
    for aid in lane_allow.mix():
        t = post_kind.targets(aid)
        assert 1 - post_kind.human_per_week(aid) / 7 <= t['abc_cap'] + t['weekly'].get('h', 0) / t['n'] + 1e-9 \
            or post_kind.human_per_week(aid) == 4


def test_kill_switch_kind(monkeypatch):
    monkeypatch.setenv('FD_POST_KIND', '0')
    assert not post_kind.needs_human('crypto_diary_zh', {})
    assert not post_kind.diary_enabled()


@needs_mix
def test_choose_kind_respects_lanes():
    k = post_kind.choose_kind('crypto_meme_en', {'c': 5}, text='pump.fun volume')
    assert k == 'meme'   # f is the meme lane's biggest human target
    k2 = post_kind.choose_kind('crypto_macro_en', {'c': 5}, text='Fed holds')
    assert k2 != 'meme'   # meme only on meme lanes
    k3 = post_kind.choose_kind('zh_industry', {'c': 5}, text='英伟达 CEO 黄仁勋表示')
    assert k3 in post_kind.HUMAN


def test_post_format_and_rules():
    f = post_kind.post_format('reaction', 'zh')
    assert f['kind'] == 'reaction' and f['no_nat'] and f['shapes'] == ['reaction']
    for k in post_kind.HUMAN:
        assert post_kind.rule(k, 'en')
        assert post_kind.rule(k, 'zh')
    assert 'never invent' in post_kind.rule('diary', 'en').lower()


@needs_mix
def test_persona_life_hook_off_by_default(monkeypatch):
    monkeypatch.setitem(lane_allow.cfg('crypto_diary_zh'), 'persona_life_details', ['lives in Chengdu'])
    assert 'Chengdu' not in post_kind.rule('diary', 'en', 'crypto_diary_zh')
    monkeypatch.setenv('FD_PERSONA_LIFE', '1')
    assert 'Chengdu' in post_kind.rule('diary', 'en', 'crypto_diary_zh')
    monkeypatch.setitem(lane_allow.cfg('crypto_diary_zh'), 'persona_life_details', [])


def test_bio_findings():
    assert post_kind.bio_findings('今天又没忍住看盘，比特币又跌了', 'zh', 'diary') == []
    assert post_kind.bio_findings('我刚买了一点 BTC', 'zh', 'diary')[0]['code'] == 'kind_invented_bio'
    assert post_kind.bio_findings('I just bought the dip, my bags are heavy', 'en', 'reaction')
    assert post_kind.bio_findings('refreshed the chart way too many times today', 'en', 'diary') == []
    assert post_kind.bio_findings('我刚买了一点 BTC', 'zh', None) == []   # analysis kinds: other checks own this


def test_row_kind_legacy_guess():
    assert post_kind.row_kind({'kind': 'meme'}) == 'meme'
    assert post_kind.row_kind({'post_format': {'type': 'list_dump'}}) == 'a'
    assert post_kind.row_kind({'post_format': {'type': 'quick_take'}, 'body': 'a take'}) == 'c'
    counts = post_kind.week_counts('x', [{'account_id': 'x', 'kind': 'reaction'},
                                         {'account_id': 'x', 'post_mode': 'reply'},
                                         {'account_id': 'y', 'kind': 'meme'}])
    assert counts == {'reaction': 1}


def test_format_block_carries_kind_rule():
    from types import SimpleNamespace
    from live import posting_habits as ph
    persona = SimpleNamespace(lang='en', persona_id='crypto_meme_en')
    fmt = dict(post_kind.post_format('meme', 'en'), kind_account='crypto_meme_en', offlane_aside=True)
    block = ph.format_block(persona, fmt, card={'per_type_habits': {}, 'punctuation': {}}, posts_dir='/nonexistent')
    assert block['kind'] == 'meme' and 'meme' in block['kind_rule'].lower()
    assert 'offlane_rule' in block


# ---------------------------------------------------------------- select() integration
def _sel(monkeypatch, pools, accounts, labels, history=()):
    import importlib.util
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('dc_audit', Path(__file__).resolve().parents[1] / 'scripts' / 'daily_compose.py')
    dc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dc)
    ref = datetime(2026, 10, 12, 4, tzinfo=timezone.utc)
    for k, v in {'FD_TOPIC_DIV': '0', 'FD_HOTSPOT': '0', 'FD_SLOT_RULE': '0', 'FD_HEAT': '0', 'FD_X_BREADTH': '0',
                 'FD_LANE_FIT': '0', 'FD_TWIN_RULE': '1'}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(sd, 'history_rows', lambda day, **k: list(history))
    monkeypatch.setattr(sl, 'label_many', lambda texts, **k: ({}, {}))
    monkeypatch.setattr(sl, 'get', lambda text, path=None: next((v for k, v in labels.items() if k in text), None))
    monkeypatch.setattr(dc, 'MAX_ACCOUNTS_PER_EVENT', 9)
    monkeypatch.setattr(dc, 'ContentStore', lambda: None)
    monkeypatch.setattr(dc, 'candidates', lambda store, aid, *a, **k: list(pools.get(aid, [])))
    monkeypatch.setattr(dc.prescreen, 'prescreen', lambda a, g: {'ok': True})
    monkeypatch.setattr(dc, 'group_hooks', lambda g: set())
    monkeypatch.setattr(dc.demo, 'in_shelf', lambda g, now=None: True)
    monkeypatch.setattr(dc.registry, 'persona_for_account', lambda a: a)
    monkeypatch.setattr(dc.ph, 'load_card', lambda p: {'post_type_mix': {'quick_take': 1.0}})
    monkeypatch.setattr(dc.ph, 'choose_format', lambda *a, **k: {'type': 'quick_take', 'length': 'short', 'thread_parts': 1,
                                                                 'length_target': 200, 'shapes': []})
    monkeypatch.setattr(dc.ph, 'sample_post_time', lambda *a, **k: ref)
    monkeypatch.setattr(dc.topic_div, 'profiles', lambda ids, ref, day, **k: {a: {'mix': {}, 'entities_72h': {}, 'posts': 0,
                                                                                    'posts_per_day': 0, 'distinct_themes': 0,
                                                                                    'stories': 0, 'themes': {}} for a in ids})
    universes = {a['id']: {'angle_lead': {'macro_liquidity': 0.4, 'price_structure': 0.3, 'narrative_sector': 0.3},
                           'x_sources': []} for a in accounts}
    info = {}
    plan, _ = dc.select(accounts, universes, date(2026, 10, 12), 1, now=ref, info=info)
    return plan, info


def _g(i, title):
    from datetime import datetime, timezone
    src = {'id': f's{i}', 'source_hash': f'h{i}', 'title': title, 'published_at': datetime(2026, 10, 12, 1, tzinfo=timezone.utc).isoformat(),
           'publisher': f'pub{i}', 'adapter': 'rss', 'url': ''}
    return [{'unit_id': f'u{i}', 'licence_tier': 'B', 'tag_personas': [], 'source': src,
             'unit': {'kind': 'view', 'statement': title, 'numbers': []}}]


ZH3 = [{'id': a, 'lang': 'zh', 'retrieval_beats': []} for a in ('crypto_macro_zh', 'crypto_btc_cycle_zh', 'crypto_newbie_zh')]


@needs_mix
def test_select_story_cap_displaces_to_next_pick(monkeypatch):
    for k in ('FD_POST_KIND', 'FD_DIARY_SLOT'):
        monkeypatch.setenv(k, '0')
    labels = {'Robinhood': lab('Robinhood', 'buys', 'BTC', 'Robinhood buys BTC', b='btc_price_market'),
              'Strategy': lab('Strategy', 'buys', 'BTC', 'Strategy buys more BTC', b='btc_price_market'),
              'Fidelity': lab('Fidelity', 'flows', '', 'Fidelity BTC ETF inflows', b='crypto_etf_institutions')}
    shared = _g(1, 'Robinhood buys $25M of bitcoin')
    pools = {a['id']: [shared, _g(10 + i, ['Strategy buys 500 BTC', 'Fidelity ETF inflows jump', 'Strategy adds BTC'][i])]
             for i, a in enumerate(ZH3)}
    plan, info = _sel(monkeypatch, pools, ZH3, labels)
    on_robinhood = [a for a, ps in plan.items() if ps and ps[0]['title'].startswith('Robinhood')]
    assert len(on_robinhood) == 2                                    # <= 2 zh accounts per story per day
    assert all(ps for ps in plan.values())                           # the displaced account took its next pick
    assert info['audit_fixes']['skips_total'].get('story_cap_lang_day') == 1


@needs_mix
def test_select_lane_off_pick_is_handed_over(monkeypatch):
    for k in ('FD_POST_KIND', 'FD_DIARY_SLOT'):
        monkeypatch.setenv(k, '0')
    labels = {'freezes': lab('Tether', 'freezes', '', 'Tether freezes USDT', b='stablecoins_tether'),
              'meme': lab('pump.fun', 'launches', '', 'pump.fun launches app', b='memecoins_launchpads')}
    accts = [{'id': 'crypto_meme_zh', 'lang': 'zh', 'retrieval_beats': []},
             {'id': 'crypto_stable_yield_zh', 'lang': 'zh', 'retrieval_beats': []}]
    tether = _g(1, 'Tether freezes USDT wallets')
    pools = {'crypto_meme_zh': [tether, _g(2, 'pump.fun meme launches app')], 'crypto_stable_yield_zh': [tether]}
    pools['crypto_stable_yield_zh'] = []        # the stable-yield account has nothing of its own today
    plan, info = _sel(monkeypatch, pools, accts, labels)
    assert plan['crypto_meme_zh'][0]['title'].startswith('pump.fun')
    assert plan['crypto_stable_yield_zh'][0]['title'].startswith('Tether')
    assert plan['crypto_stable_yield_zh'][0]['reassigned_from'] == 'crypto_meme_zh'


@needs_mix
def test_select_diary_slot_and_kind(monkeypatch):
    labels = {'BTC': lab('Bitcoin', 'price_move', '', 'Bitcoin drops', b='btc_price_market'),
              'meme': lab('pump.fun', 'launches', '', 'pump.fun app', b='memecoins_launchpads')}
    accts = [{'id': 'crypto_diary_zh', 'lang': 'zh', 'retrieval_beats': []}]
    pools = {'crypto_diary_zh': [_g(1, 'BTC drops below 80k'), _g(2, 'meme launchpad pump.fun app')]}
    plan, info = _sel(monkeypatch, pools, accts, labels)
    ps = plan['crypto_diary_zh']
    assert len(ps) == 2 and ps[1]['slot'] == 'diary' and ps[1]['kind'] == 'diary'
    assert ps[1]['post_format']['kind'] == 'diary'
    assert info['audit_fixes']['human_kinds'].get('diary') == 1


@needs_mix
def test_diary_slot_may_share_a_packet_another_account_took(monkeypatch):
    labels = {'BTC': lab('Bitcoin', 'price_move', '', 'Bitcoin drops', b='btc_price_market'),
              'meme': lab('pump.fun', 'launches', '', 'pump.fun app', b='memecoins_launchpads')}
    accts = [{'id': 'crypto_newbie_zh', 'lang': 'zh', 'retrieval_beats': []},
             {'id': 'crypto_diary_zh', 'lang': 'zh', 'retrieval_beats': []}]
    g, g2 = _g(1, 'BTC drops below 80k'), _g(2, 'meme launchpad pump.fun app')
    plan, info = _sel(monkeypatch, {'crypto_newbie_zh': [g], 'crypto_diary_zh': [g2, g]}, accts, labels)
    assert plan['crypto_newbie_zh'][0]['title'].startswith('BTC')
    diary = [p for p in plan['crypto_diary_zh'] if p.get('slot') == 'diary']
    assert len(diary) == 1 and diary[0]['title'].startswith('BTC')   # shares the packet newbie took


def test_density_findings():
    assert post_kind.density_findings('ngl did not expect that. welp', 'en', 'reaction') == []
    assert post_kind.density_findings('BTC 80k, ETH 3k, SOL 150', 'en', 'reaction')[0]['code'] == 'kind_too_dense'
    assert post_kind.density_findings('Tether froze wallets. what would you do?', 'en', 'question') == []
    assert post_kind.density_findings('Tether froze wallets. Bad sign.', 'en', 'question')[0]['code'] == 'kind_question_no_question'
    assert post_kind.density_findings('BTC 80k, ETH 3k', 'en', None) == []


@needs_mix
def test_relax_round_keeps_an_account_with_only_donor_side_topics(monkeypatch):
    for k in ('FD_POST_KIND', 'FD_DIARY_SLOT'):
        monkeypatch.setenv(k, '0')
    sh = lane_allow.cfg('crypto_meme_en')['donor_bucket_share']
    side = next(b for b in sh if lane_allow.verdict('crypto_meme_en', b) == 'off')
    labels = {'side': lab('Acme', 'launches', '', 'Acme launches thing', b=side),
              'never': lab('Bank', 'policy', '', 'Bank policy', b='china_hk_markets')}
    accts = [{'id': 'crypto_meme_en', 'lang': 'en', 'retrieval_beats': []}]
    plan, info = _sel(monkeypatch, {'crypto_meme_en': [_g(1, 'never bank'), _g(2, 'side acme')]}, accts, labels)
    p = plan['crypto_meme_en']
    assert len(p) == 1 and p[0]['title'].startswith('side') and p[0]['lane_relaxed']
