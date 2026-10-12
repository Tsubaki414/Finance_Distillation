"""Oct 12 human-mix tuning (live/post_kind.py FD_HUMAN_MIX_TUNE + scripts/daily_compose.py kind budget).

The 10-12 measurement: of the 86 standalone draft_ready rows in the live inbox (10-10..10-12) only 2 were a human
kind (~2%) against a donor human share of ~32%, and of the 11 first standalone picks planned on 10-12 eight were
dropped by post_kind.needs_human's weekday gate alone (0 by the weekly count). These tests pin the fix:
  - the weekday is a priority, not a gate (catch-up while behind), and the kill switch restores the old rule exactly;
  - the day's human picks are capped at the donor share, so the catch-up cannot land 9/9 reactions on one day;
  - the kind is persisted on the inbox row as a first-class field;
  - a human pick keeps its own short format, and text that came back as a data / news take is flagged + re-format;
  - nothing here injects persona-life text (no city / pets / job / trades) - the bio check stays HARD.
"""
from datetime import date, timedelta

import pytest

from live import lane_allow, post_kind

needs_mix = pytest.mark.skipif(not lane_allow.PATH.exists(), reason='local account_mix.json not built')


@pytest.fixture(autouse=True)
def mix_on(monkeypatch):
    """tests/conftest.py turns the Oct 11 audit fixes off for the scripted selection tests; this file exercises them."""
    monkeypatch.setenv('FD_POST_KIND', '1')
    monkeypatch.setenv('FD_DIARY_SLOT', '1')


def test_kill_switch_default_on_and_off(monkeypatch):
    monkeypatch.delenv('FD_HUMAN_MIX_TUNE', raising=False)
    assert post_kind.tune_enabled()
    monkeypatch.setenv('FD_HUMAN_MIX_TUNE', '0')
    assert not post_kind.tune_enabled()
    monkeypatch.setenv('FD_HUMAN_MIX_TUNE', '1')
    assert post_kind.tune_enabled()


@needs_mix
def test_weekday_is_a_priority_not_a_gate(monkeypatch):
    """An account behind its target with no human post in the window qualifies on a non-weekday; with the switch off
    the same call is the Oct 11 weekday gate."""
    monkeypatch.delenv('FD_HUMAN_MIX_TUNE', raising=False)
    aid = 'crypto_meme_en'
    days = [date(2026, 10, 12) + timedelta(days=i) for i in range(7)]
    off = next(d for d in days if d.toordinal() % 7 not in post_kind.human_days(aid))
    assert post_kind.needs_human(aid, {'c': 5}, day=off, since_human=None)      # catch-up
    monkeypatch.setenv('FD_HUMAN_MIX_TUNE', '0')
    assert not post_kind.needs_human(aid, {'c': 5}, day=off, since_human=None)  # old behaviour


@needs_mix
def test_kill_switch_off_matches_the_old_rule_exactly(monkeypatch):
    """FD_HUMAN_MIX_TUNE=0 must reproduce the Oct 11 gate for every account/day pair: on == weekday, and the
    count/human_per_week ceiling first."""
    monkeypatch.setenv('FD_HUMAN_MIX_TUNE', '0')
    days = [date(2026, 10, 12) + timedelta(days=i) for i in range(14)]
    for aid in list(lane_allow.mix()):
        for d in days:
            expect = d.toordinal() % 7 in post_kind.human_days(aid)
            assert post_kind.needs_human(aid, {'c': 5}, day=d, since_human=6) == expect
        # the weekly human target still caps it, switch or no switch
        assert not post_kind.needs_human(aid, {'diary': post_kind.human_per_week(aid)}, day=days[0], since_human=6)


@needs_mix
def test_catch_up_never_exceeds_the_weekly_target(monkeypatch):
    monkeypatch.delenv('FD_HUMAN_MIX_TUNE', raising=False)
    aid = 'crypto_meme_en'
    d = date(2026, 10, 15)
    n = post_kind.human_per_week(aid)
    assert not post_kind.needs_human(aid, {'diary': n}, day=d, since_human=6)        # target met
    assert post_kind.needs_human(aid, {'diary': n - 1}, day=d, since_human=post_kind.due_gap(aid))


@needs_mix
def test_due_gap_tracks_human_per_week(monkeypatch):
    for aid in list(lane_allow.mix()):
        k = post_kind.human_per_week(aid)
        assert post_kind.due_gap(aid) == max(1, round(7.0 / k))
        assert 1 <= post_kind.due_gap(aid) <= 4


@needs_mix
def test_human_priority_puts_the_spread_day_first(monkeypatch):
    monkeypatch.delenv('FD_HUMAN_MIX_TUNE', raising=False)
    aid = 'crypto_meme_en'
    days = [date(2026, 10, 12) + timedelta(days=i) for i in range(7)]
    on = next(d for d in days if d.toordinal() % 7 in post_kind.human_days(aid))
    off = next(d for d in days if d.toordinal() % 7 not in post_kind.human_days(aid))
    assert post_kind.human_priority(aid, {'c': 5}, on)[0] > post_kind.human_priority(aid, {'c': 5}, off)[0]


@needs_mix
def test_days_since_human_reads_the_history(monkeypatch):
    monkeypatch.delenv('FD_HUMAN_MIX_TUNE', raising=False)
    d = date(2026, 10, 12)
    rows = [{'account_id': 'crypto_meme_en', 'day': '2026-10-09', 'kind': 'reaction', 'draft_status': 'draft_ready',
             'text': 'x'}]
    assert post_kind.days_since_human('crypto_meme_en', rows, d) == 3
    assert post_kind.days_since_human('crypto_meme_en', [], d) is None
    assert post_kind.days_since_human('other', rows, d) is None


@needs_mix
def test_choose_kind_respects_exclude(monkeypatch):
    """The planner reserves 'diary' for a diary-lane account's own daily diary slot."""
    monkeypatch.delenv('FD_HUMAN_MIX_TUNE', raising=False)
    k = post_kind.choose_kind('crypto_diary_zh', {'c': 5}, text='BTC drops', exclude=('diary',))
    assert k in post_kind.HUMAN and k != 'diary'
    assert post_kind.choose_kind('crypto_diary_zh', {'c': 5}, text='BTC drops') == 'diary'


# ---------------------------------------------------------------- compose format + row persistence
def test_post_format_is_short_and_locked(monkeypatch):
    monkeypatch.delenv('FD_HUMAN_MIX_TUNE', raising=False)
    fmt = post_kind.post_format('reaction', 'en')
    assert fmt['type'] == 'one_liner' and fmt['length'] == 'short' and fmt['shapes'] == ['reaction']
    assert fmt['length_target'] == {'min': 20, 'max': 140} and fmt['kind'] == 'reaction' and fmt['no_nat']
    assert fmt['kind_locked'] is True
    monkeypatch.setenv('FD_HUMAN_MIX_TUNE', '0')
    assert 'kind_locked' not in post_kind.post_format('reaction', 'en')


def test_relocked_restores_the_kind_format(monkeypatch):
    monkeypatch.delenv('FD_HUMAN_MIX_TUNE', raising=False)
    row = {'lang': 'en', 'post_format': {'type': 'list_dump', 'shapes': ['data_dump'], 'kind': None,
                                         'length': 'long', 'length_target': {'min': 300, 'max': 900}}}
    assert post_kind.relocked(row, 'reaction')
    f = row['post_format']
    assert f['type'] == 'one_liner' and f['shapes'] == ['reaction'] and f['kind'] == 'reaction'
    assert f['length'] == 'short' and f['kind_relocked'] and f['length_target']['max'] == 900   # never narrows a cap
    assert not post_kind.relocked(row, 'reaction')          # already correct
    assert not post_kind.relocked(row, 'c')                 # analytic kinds are not touched
    monkeypatch.setenv('FD_HUMAN_MIX_TUNE', '0')
    assert not post_kind.relocked({'lang': 'en', 'post_format': {'type': 'list_dump'}}, 'reaction')


def test_was_relabelled_flags_a_data_take_only(monkeypatch):
    monkeypatch.delenv('FD_HUMAN_MIX_TUNE', raising=False)
    assert post_kind.was_relabelled('ngl did not expect that. welp', 'en', 'reaction') == []
    assert post_kind.was_relabelled('BTC 80k, ETH 3k, SOL 150, TON 5', 'en', 'reaction')[0]['code'] == \
        'kind_read_as_data_take'
    assert post_kind.was_relabelled('BTC 80k, ETH 3k', 'en', 'c') == []          # not a human kind
    monkeypatch.setenv('FD_HUMAN_MIX_TUNE', '0')
    assert post_kind.was_relabelled('1 2 3 4 5 6', 'en', 'reaction') == []


def test_no_persona_life_text_in_any_human_rule():
    """No city / pets / job / backstory / trades anywhere in the kind rules or the format: the human kinds are
    reactions and questions about real events, never invented biography."""
    banned = ('my dog', 'my cat', 'pets', 'my city', 'live in', 'my job', 'my boss', 'my office', 'my apartment',
              'i bought', 'i sold', 'my position', 'my portfolio', 'my p&l', '养了', '我家', '上班', '公司里', '老板')
    for kind in post_kind.HUMAN:
        for lang in ('en', 'zh'):
            text = (post_kind.rule(kind, lang) or '') + (post_kind.OFFLANE_RULE[1 if lang == 'zh' else 0])
            low = text.lower()
            for bad in banned:
                assert bad not in low, (kind, lang, bad)
        fmt = post_kind.post_format(kind, 'en')
        assert 'persona' not in str(fmt).lower()
    assert 'persona_life' not in str(post_kind.post_format('diary', 'zh')).lower()
    # and the HARD invented-biography check still bites on a human kind
    assert post_kind.bio_findings('I just bought the dip, my bags are heavy', 'en', 'reaction')
    assert post_kind.bio_findings('今天又没忍住看盘，比特币又跌了', 'zh', 'diary') == []


# ---------------------------------------------------------------- the planner path (select) + row
def _sel(monkeypatch, pools, accounts, labels, history=()):
    import importlib.util
    from datetime import datetime, timezone
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        'dc_human_mix', Path(__file__).resolve().parents[1] / 'scripts' / 'daily_compose.py')
    dc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dc)
    from live import story_dedupe as sd, story_label as sl
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
    monkeypatch.setattr(dc.ph, 'choose_format', lambda *a, **k: {'type': 'quick_take', 'length': 'short',
                                                                 'thread_parts': 1, 'length_target': 200,
                                                                 'shapes': []})
    monkeypatch.setattr(dc.ph, 'sample_post_time', lambda *a, **k: ref)
    monkeypatch.setattr(dc.topic_div, 'profiles', lambda ids, ref, day, **k: {
        a: {'mix': {}, 'entities_72h': {}, 'posts': 0, 'posts_per_day': 0, 'distinct_themes': 0, 'stories': 0,
            'themes': {}} for a in ids})
    universes = {a['id']: {'angle_lead': {'macro_liquidity': 0.4, 'price_structure': 0.3, 'narrative_sector': 0.3},
                           'x_sources': []} for a in accounts}
    info = {}
    plan, _ = dc.select(accounts, universes, date(2026, 10, 12), 1, now=ref, info=info)
    return plan, info, dc


def _g(i, title):
    from datetime import datetime, timezone
    src = {'id': f's{i}', 'source_hash': f'h{i}', 'title': title,
           'published_at': datetime(2026, 10, 12, 1, tzinfo=timezone.utc).isoformat(),
           'publisher': f'pub{i}', 'adapter': 'rss', 'url': ''}
    return [{'unit_id': f'u{i}', 'licence_tier': 'B', 'tag_personas': [], 'source': src,
             'unit': {'kind': 'view', 'statement': title, 'numbers': []}}]


def lab(name, verb, obj, title, b=None):
    return {'entities': [name], 'event_key': f'{name}:{verb}', 'bucket': b, 'title': title}


@needs_mix
def test_plan_gives_human_kinds_to_behind_accounts(monkeypatch):
    """With the tuning on, the standalone picks of accounts behind their human target carry human kinds."""
    monkeypatch.delenv('FD_HUMAN_MIX_TUNE', raising=False)
    labels = {'BTC': lab('Bitcoin', 'price_move', '', 'Bitcoin drops', b='btc_price_market'),
              'ETH': lab('Ethereum', 'price_move', '', 'ETH drops', b='eth_price_market'),
              'meme': lab('pump.fun', 'launches', '', 'pump.fun app', b='memecoins_launchpads')}
    ids = ['crypto_meme_zh', 'crypto_btc_cycle_zh', 'crypto_altcoin_zh', 'zh_macro', 'crypto_research_zh']
    accts = [{'id': a, 'lang': 'zh', 'retrieval_beats': []} for a in ids]
    pools = {a: [_g(i, t) for i, t in enumerate(('BTC drops below 80k', 'ETH drops 4%', 'pump.fun app'),
                                                start=1)] for a in ids}
    plan, info, _dc = _sel(monkeypatch, pools, accts, labels)
    kinds = {a: (plan[a][0].get('post_format') or {}).get('kind') for a in ids}
    human = [a for a, k in kinds.items() if k in post_kind.HUMAN]
    assert human, kinds
    # every human pick carries the kind's own short format, not the habit card's quick_take
    for a in human:
        fmt = plan[a][0]['post_format']
        assert fmt['type'] == post_kind._FORMAT[kinds[a]][0]
        assert fmt['kind'] == kinds[a] and fmt['kind_locked'] is True and fmt['length'] == 'short'
        assert plan[a][0]['kind'] == kinds[a]
    # the day's human picks stay near the donor share, not all of them
    share = sum(post_kind.targets(a)['human_share'] for a in ids) / len(ids)
    assert len(human) <= max(1, round(share * len(ids))) + 1
    assert info['audit_fixes']['human_kinds']


@needs_mix
def test_plan_kill_switch_restores_the_old_weekday_gate(monkeypatch):
    """FD_HUMAN_MIX_TUNE=0: no standalone pick of an account whose day is not a human weekday gets a human kind
    (the diary-lane account's own daily diary slot is the Oct 11 feature and is not part of this switch)."""
    monkeypatch.setenv('FD_HUMAN_MIX_TUNE', '0')
    labels = {'BTC': lab('Bitcoin', 'price_move', '', 'Bitcoin drops', b='btc_price_market')}
    ids = [a for a in lane_allow.mix()
           if date(2026, 10, 12).toordinal() % 7 not in post_kind.human_days(a) and not post_kind.is_diary_account(a)][:6]
    accts = [{'id': a, 'lang': 'en', 'retrieval_beats': []} for a in ids]
    pools = {a: [_g(1, 'BTC drops below 80k')] for a in ids}
    plan, _info, _dc = _sel(monkeypatch, pools, accts, labels)
    for a in ids:
        for p in plan.get(a) or []:
            assert (p.get('post_format') or {}).get('kind') is None, a


@needs_mix
def test_plan_tune_on_gives_the_same_accounts_a_human_kind(monkeypatch):
    """The same accounts, same day, switch on: the picks carry human kinds (the catch-up)."""
    monkeypatch.delenv('FD_HUMAN_MIX_TUNE', raising=False)
    labels = {'BTC': lab('Bitcoin', 'price_move', '', 'Bitcoin drops', b='btc_price_market')}
    ids = [a for a in lane_allow.mix()
           if date(2026, 10, 12).toordinal() % 7 not in post_kind.human_days(a) and not post_kind.is_diary_account(a)][:6]
    accts = [{'id': a, 'lang': 'en', 'retrieval_beats': []} for a in ids]
    pools = {a: [_g(1, 'BTC drops below 80k')] for a in ids}
    plan, _info, _dc = _sel(monkeypatch, pools, accts, labels)
    got = [a for a in ids if ((plan.get(a) or [{}])[0].get('post_format') or {}).get('kind') in post_kind.HUMAN]
    assert got, {a: ((plan.get(a) or [{}])[0].get('post_format') or {}).get('kind') for a in ids}
    # the day's budget is the donor share of the picks, so not every one of them
    share = sum(post_kind.targets(a)['human_share'] for a in ids) / len(ids)
    assert len(got) <= max(1, round(share * len(ids)))


def test_inbox_row_persists_the_kind(monkeypatch):
    """The row carries the pick's kind as a first-class field, so the mix counters never depend on the legacy guess."""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        'dc_row', Path(__file__).resolve().parents[1] / 'scripts' / 'daily_compose.py')
    dc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dc)
    res = {'id': 'd1', 'body': 'ngl did not expect that', 'text': 't', 'post_type': 'one_liner',
           'plan': {'source_id': 's1', 'post_format': {'type': 'one_liner', 'kind': 'reaction', 'kind_locked': True},
                    'suggested_post_time_london': '2026-10-12T10:00:00+01:00', 'angle_why': '',
                    'shared_event_with': [], 'kind': 'reaction', 'slot': 'diary'},
           'source': {}, 'arbitration': {}, 'hard_repair': {}}
    cfg = {'id': 'crypto_meme_en', 'no': 1, 'name': 'n', 'beat': 'b', 'lang': 'en'}
    row = dc.inbox_row(res, cfg, date(2026, 10, 12), 'run1')
    assert row['kind'] == 'reaction' and row['slot'] == 'diary'
    assert post_kind.row_kind(row) == 'reaction'
    assert post_kind.is_human(post_kind.row_kind(row))
