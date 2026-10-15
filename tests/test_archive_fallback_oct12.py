"""Oct 12 (Fiona, option 2; FD_ARCHIVE_FALLBACK_ONLY): 回看 / 常青 only takes the standalone slot when the account has
no fresh standalone candidate. Switch off == old behaviour."""
import importlib.util
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from live import archive_fallback as af, archive_lookback as al, compose_inbox, story_dedupe as sd, story_label as sl

ROOT = Path(__file__).resolve().parents[1]
DAY = '2026-10-12'
ACCT = 'crypto_meme_zh'


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv('FD_COMPOSE_INBOX', str(tmp_path / 'inbox'))
    monkeypatch.setenv('FD_STORY_STORE', str(tmp_path / 'labels'))
    for k in ('FD_ARCHIVE_FALLBACK_ONLY', 'FD_ARCHIVE', 'FD_ARCHIVE_ACCOUNTS', 'FD_HOLD_STATUS_SYNC',
              'FD_OFFLANE_REPICK', 'FD_STORY_DEDUPE', 'FD_LANE_ALLOW', 'FD_POST_KIND', 'FD_DIARY_SLOT'):
        monkeypatch.delenv(k, raising=False)
    sl._CACHE.clear()
    sl._LOADED.clear()


def _dc(name='dc_archive_fb'):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / 'daily_compose.py')
    dc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dc)
    return dc


def _arc(i='a1', account=ACCT, **kw):
    return {'id': f'arc-000001-{account}-{i}', 'day': DAY, 'account_id': account, 'post_kind': 'archive_lookback',
            'text': 'then vs now', 'draft_status': 'draft_ready', 'held': False, 'hold_reason': None,
            'source': {'id': f'x_h_{i}', 'title': 'old post'}, **kw}


def _fresh(i, account=ACCT, **kw):
    return {'id': f'compose-{i}', 'day': DAY, 'account_id': account, 'text': 'fresh draft',
            'draft_status': 'draft_ready', 'held': False, 'hold_reason': None,
            'source': {'id': f's{i}', 'title': f'title {i}'}, **kw}


def _eng(i, account=ACCT):
    return _fresh(i, account, engagement={'mode': 'reply'}, source={'id': f'x-{i}00', 'title': 't'})


# ---------------------------------------------------------------- module rules
def test_switch_default_on_and_off():
    assert af.enabled({}) and af.enabled({'FD_ARCHIVE_FALLBACK_ONLY': '1'})
    assert not af.enabled({'FD_ARCHIVE_FALLBACK_ONLY': '0'})


def test_is_archive_by_kind_or_id():
    assert af.is_archive({'post_kind': 'archive_lookback'})
    assert af.is_archive({'id': 'evg-123-x-1'}) and af.is_archive({'id': 'arc-1'})
    assert not af.is_archive(_fresh(1))


def test_displaceable_only_when_every_ready_standalone_is_a_pending_archive_row():
    rows = [_arc('a', 'A'), _eng(1, 'A'),                       # archive + engagement: archive yields
            _arc('b', 'B'), _fresh(2, 'B'),                     # fresh standalone already there: nothing to yield
            _arc('c', 'C', review_status='approved'),           # reviewed: never
            _arc('d', 'D', published=True),                     # published: never
            _arc('e', 'E', held=True),                          # held archive does not hold the slot anyway
            _arc('f', 'F'), _fresh(3, 'F', slot='diary')]       # diary row is its own slot
    out = af.displaceable(rows)
    assert out == {'A': [_arc('a', 'A')['id']], 'F': [_arc('f', 'F')['id']]}
    pub = af.displaceable([_arc('g', 'G')], published=lambda r: True)
    assert pub == {}


def test_skip_accounts_from_last_round_state():
    last = {'A': {'round': 2, 'standalone_left': 3}, 'B': {'round': 2, 'standalone_left': 0}, 'C': {'round': 0}}
    out = af.skip_accounts(last)
    assert set(out) == {'A'} and out['A'].startswith('archive_fallback: 3 fresh standalone')


# ---------------------------------------------------------------- part 1: archive hook skips
def _fake_run(calls):
    def run(ids, day, **kw):
        calls.append(list(ids))
        return {'day': day, 'accounts': {a: {} for a in ids}}
    return run


def test_fill_gaps_skips_accounts_with_fresh_candidates(monkeypatch):
    calls = []
    monkeypatch.setattr(al, 'run', _fake_run(calls))
    monkeypatch.setattr(al, 'enabled_accounts', lambda config=None, environ=None: ['A', 'B', 'C'])
    out = al.fill_gaps(DAY, accounts=['A', 'B', 'C'], log=lambda *a: None, skip={'A': 'archive_fallback: 2 fresh'})
    assert calls == [['B', 'C']]
    assert out['fallback_skipped'] == {'A': 'archive_fallback: 2 fresh'}


def test_fill_gaps_all_skipped_runs_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(al, 'run', _fake_run(calls))
    monkeypatch.setattr(al, 'enabled_accounts', lambda config=None, environ=None: ['A'])
    out = al.fill_gaps(DAY, accounts=['A'], log=lambda *a: None, skip={'A': 'x'})
    assert calls == [] and out['fallback_skipped'] == {'A': 'x'}


def test_fill_gaps_without_skip_is_old_behaviour(monkeypatch):
    calls = []
    monkeypatch.setattr(al, 'run', _fake_run(calls))
    monkeypatch.setattr(al, 'enabled_accounts', lambda config=None, environ=None: ['A', 'B'])
    out = al.fill_gaps(DAY, accounts=['A', 'B'], log=lambda *a: None)
    assert calls == [['A', 'B']] and 'fallback_skipped' not in out


# ---------------------------------------------------------------- select harness (zero model)
def _g(i, title, sid=None):
    src = {'id': sid or f's{i}', 'source_hash': f'h{i}', 'title': title, 'publisher': f'pub{i}', 'adapter': 'rss',
           'url': '', 'published_at': datetime(2026, 10, 12, 1, tzinfo=timezone.utc).isoformat()}
    return [{'unit_id': f'u{i}', 'licence_tier': 'B', 'tag_personas': [], 'source': src,
             'unit': {'kind': 'view', 'statement': title, 'numbers': []}}]


def _sel(monkeypatch, pools, inbox=(), archive_yield=None, done=None):
    dc = _dc('dc_archive_fb_sel')
    ref = datetime(2026, 10, 12, 4, tzinfo=timezone.utc)
    for k, v in {'FD_TOPIC_DIV': '0', 'FD_HOTSPOT': '0', 'FD_SLOT_RULE': '1', 'FD_ENGAGE_PICK_GATE': '0',
                 'FD_HEAT': '0', 'FD_X_BREADTH': '0', 'FD_ENGAGE_FETCH': '0', 'FD_LANE_FIT': '0',
                 'FD_TWIN_RULE': '0', 'FD_POST_KIND': '0', 'FD_DIARY_SLOT': '0', 'FD_STORY_DEDUPE': '0',
                 'FD_LANE_ALLOW': '0', 'FD_FRESH_GATE': '0'}.items():
        monkeypatch.setenv(k, v)
    for r in inbox:
        compose_inbox.add(r)
    monkeypatch.setattr(sd, 'history_rows', lambda day, **k: [])
    monkeypatch.setattr(sl, 'label_many', lambda texts, **k: ({}, {}))
    monkeypatch.setattr(sl, 'get', lambda text, path=None: None)
    monkeypatch.setattr(dc, 'MAX_ACCOUNTS_PER_EVENT', 9)
    monkeypatch.setattr(dc, 'ContentStore', lambda: None)
    monkeypatch.setattr(dc, 'candidates', lambda store, aid, *a, **k: list(pools.get(aid, [])))
    monkeypatch.setattr(dc.prescreen, 'prescreen', lambda a, g: {'ok': True})
    monkeypatch.setattr(dc, 'group_hooks', lambda g: set())
    monkeypatch.setattr(dc.demo, 'in_shelf', lambda g, now=None: True)
    monkeypatch.setattr(dc.registry, 'persona_for_account', lambda a: a)
    monkeypatch.setattr(dc.ph, 'load_card', lambda p: {'post_type_mix': {'quick_take': 1.0}})
    monkeypatch.setattr(dc.ph, 'choose_format', lambda *a, **k: {'type': 'quick_take', 'length': 'short',
                                                                 'thread_parts': 1, 'length_target': 200, 'shapes': []})
    monkeypatch.setattr(dc.ph, 'sample_post_time', lambda *a, **k: ref)
    accounts = [{'id': a, 'lang': 'zh', 'retrieval_beats': []} for a in pools]
    universes = {a['id']: {'angle_lead': {'macro_liquidity': 0.4, 'price_structure': 0.3, 'narrative_sector': 0.3},
                           'x_sources': []} for a in accounts}
    info = {}
    plan, _ = dc.select(accounts, universes, date(2026, 10, 12), 2, cap=2, done=done, now=ref, info=info,
                        archive_yield=archive_yield)
    return dc, plan, info


def test_select_reports_post_gate_standalone_pool(monkeypatch):
    pools = {ACCT: [_g(1, 'Alpha news one'), _g(2, 'Beta news two', sid='x-1234567')]}
    _dc_, _plan, info = _sel(monkeypatch, pools)
    assert info['standalone_pool_sizes'] == {ACCT: 1} and info['pool_sizes'] == {ACCT: 2}


def test_select_switch_off_has_no_new_plan_keys(monkeypatch):
    monkeypatch.setenv('FD_ARCHIVE_FALLBACK_ONLY', '0')
    _dc_, _plan, info = _sel(monkeypatch, {ACCT: [_g(1, 'Alpha news one')]}, archive_yield={})
    assert 'standalone_pool_sizes' not in info and 'archive_yield' not in info


# ---------------------------------------------------------------- part 2: fill round reopens the slot
def test_archive_row_blocks_fresh_pick_without_yield(monkeypatch):
    monkeypatch.setenv('FD_SECOND_STANDALONE', '0')   # Oct 15: legacy one-standalone slot pinned
    arc = _arc('z')
    _dc_, plan, _info = _sel(monkeypatch, {ACCT: [_g(1, 'Alpha news one')]}, inbox=[arc], done={ACCT: 1})
    assert plan[ACCT] == []                                    # old behaviour: the archive row holds the slot


def test_yield_lets_a_fresh_standalone_take_the_slot(monkeypatch):
    arc = _arc('z')
    yield_map = {ACCT: [arc['id']]}
    _dc_, plan, info = _sel(monkeypatch, {ACCT: [_g(1, 'Alpha news one')]}, inbox=[arc], done={ACCT: 0},
                            archive_yield=yield_map)
    assert [p['source_id'] for p in plan[ACCT]] == ['s1']
    assert info['archive_yield'] == yield_map


def test_yield_does_not_open_a_slot_held_by_a_fresh_row(monkeypatch):
    arc, fresh = _arc('z'), _fresh(9)
    _dc_, plan, _info = _sel(monkeypatch, {ACCT: [_g(1, 'Alpha news one')]}, inbox=[arc, fresh], done={ACCT: 0},
                             archive_yield={})
    assert plan[ACCT] == []


def test_archive_yield_map_and_ready_counts(monkeypatch):
    dc = _dc()
    monkeypatch.setattr(dc, 'admin_decisions', lambda day_s: {})
    arc = _arc('z')
    for r in (arc, _eng(1)):
        compose_inbox.add(r)
    ymap = dc.archive_yield_map(date(2026, 10, 12))
    assert ymap == {ACCT: [arc['id']]}
    ready = dc.drafted_today(date(2026, 10, 12), ready_only=True)
    assert ready == {ACCT: 2} and dc.without_yield(ready, ymap) == {ACCT: 1}
    monkeypatch.setenv('FD_ARCHIVE_FALLBACK_ONLY', '0')
    assert dc.archive_yield_map(date(2026, 10, 12)) == {}
    assert dc.without_yield(ready, {}) is ready


def test_archive_yield_map_respects_published_decision(monkeypatch):
    dc = _dc()
    arc = _arc('z')
    compose_inbox.add(arc)
    monkeypatch.setattr(dc, 'admin_decisions', lambda day_s: {arc['id']: {'published': True}})
    assert dc.archive_yield_map(date(2026, 10, 12)) == {}


def test_fresh_ready_row_supersedes_pending_archive_row():
    arc = _arc('z')
    compose_inbox.add(arc)
    fresh = _fresh(1)
    compose_inbox.add(fresh)
    assert af.supersede_for(fresh, [arc['id']]) == [arc['id']]
    stored = compose_inbox.get(arc['id'])
    assert stored['superseded'] and stored['superseded_by'] == fresh['id']
    assert stored['superseded_reason'] == 'archive_fallback'


@pytest.mark.parametrize('kw', [{'review_status': 'approved'}, {'published': True}])
def test_reviewed_or_published_archive_row_is_never_superseded(kw):
    arc = _arc('z', **kw)
    compose_inbox.add(arc)
    assert af.supersede_for(_fresh(1), [arc['id']]) == []
    assert not compose_inbox.get(arc['id']).get('superseded')


def test_published_by_admin_decision_is_never_superseded():
    arc = _arc('z')
    compose_inbox.add(arc)
    assert af.supersede_for(_fresh(1), [arc['id']], published=lambda r: True) == []


@pytest.mark.parametrize('new', [_fresh(1, held=True, hold_reason='off_lane: x'), _eng(1), _arc('y'),
                                 _fresh(1, draft_status='needs_review'), _fresh(1, account='OTHER')])
def test_only_a_ready_fresh_standalone_of_the_same_account_supersedes(new):
    arc = _arc('z')
    compose_inbox.add(arc)
    assert af.supersede_for(new, [arc['id']]) == []
    assert not compose_inbox.get(arc['id']).get('superseded')


def test_supersede_wiring_in_run_round_source():
    """The run_round hook calls supersede_for only for accounts in this round's yield map (off: map is {})."""
    src = (ROOT / 'scripts' / 'daily_compose.py').read_text()
    assert "if arc_yield.get(row['account_id']):" in src
    assert "arc_yield = archive_yield_map(args.day) if (fill or args.midday) else {}" in src
    assert "**({'skip': _skip} if _skip is not None else {})" in src
