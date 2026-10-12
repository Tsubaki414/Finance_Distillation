"""Oct 12: compose-path HOLDs write needs_review (FD_HOLD_STATUS_SYNC) and no off_lane re-pick across --fill rounds
(FD_OFFLANE_REPICK). Switch off == old behaviour."""
import importlib.util
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from live import compose_inbox, lane_allow, offlane_repick, story_dedupe as sd, story_label as sl

ROOT = Path(__file__).resolve().parents[1]
needs_mix = pytest.mark.skipif(not lane_allow.PATH.exists(), reason='local account_mix.json not built')
DAY = '2026-10-12'


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv('FD_COMPOSE_INBOX', str(tmp_path / 'inbox'))
    monkeypatch.setenv('FD_STORY_STORE', str(tmp_path / 'labels'))
    for k in ('FD_HOLD_STATUS_SYNC', 'FD_OFFLANE_REPICK', 'FD_STORY_DEDUPE', 'FD_LANE_ALLOW', 'FD_POST_KIND',
              'FD_DIARY_SLOT', 'FD_STORY_PER_LANG_DAY', 'FD_STORY_72H', 'FD_TWIN_RULE'):
        monkeypatch.delenv(k, raising=False)
    sl._CACHE.clear()
    sl._LOADED.clear()


def _dc(name='dc_offlane'):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / 'daily_compose.py')
    dc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dc)
    return dc


def _row(i, **kw):
    return {'id': f'compose-{i}', 'day': DAY, 'account_id': kw.pop('account_id', 'crypto_btc_cycle_zh'),
            'text': 'draft text', 'draft_status': 'draft_ready', 'held': False, 'hold_reason': None,
            'source': {'id': f's{i}', 'title': f'title {i}'}, **kw}


def _stored(i):
    return json.loads((Path(compose_inbox.root()) / DAY / f'compose-{i}.json').read_text())


# ---------------------------------------------------------------- A: hold -> needs_review
@pytest.mark.parametrize('reason', ['off_lane: no BTC / ETH driver', 'arbitration', 'hard: stale_event_unframed',
                                    'fix1012 rescan: fresh_gate'])
def test_held_row_is_written_needs_review(reason):
    compose_inbox.add(_row(1, held=True, hold_reason=reason))
    r = _stored(1)
    assert r['held'] is True and r['hold_reason'] == reason          # which rows are held: unchanged
    assert r['draft_status'] == 'needs_review' and r['publishable'] is False
    assert r['hold_status_from'] == 'draft_ready'


def test_switch_off_keeps_old_row_exactly(monkeypatch):
    monkeypatch.setenv('FD_HOLD_STATUS_SYNC', '0')
    row = _row(1, held=True, hold_reason='off_lane: x')
    before = dict(row)
    compose_inbox.add(row)
    r = _stored(1)
    assert row == before                                              # caller's row untouched
    assert r['draft_status'] == 'draft_ready' and 'hold_status_from' not in r


def test_not_held_superseded_and_other_statuses_untouched():
    compose_inbox.add(_row(1))
    compose_inbox.add(_row(2, held=True, superseded=True, hold_reason='off_lane: x'))
    compose_inbox.add(_row(3, held=True, hold_reason='hard: x', draft_status='blocked'))
    compose_inbox.add(_row(4, held=True, hold_reason='hard: y', draft_status='needs_review'))
    assert _stored(1)['draft_status'] == 'draft_ready' and not _stored(1)['held']
    assert _stored(2)['draft_status'] == 'draft_ready'                # superseded is its own state
    assert _stored(3)['draft_status'] == 'blocked'
    assert _stored(4)['draft_status'] == 'needs_review' and 'hold_status_from' not in _stored(4)


def test_sync_is_in_place_so_later_readers_see_it():
    row = _row(1, held=True, hold_reason='arbitration')
    compose_inbox.add(row)
    assert row['draft_status'] == 'needs_review'                      # daily_compose keeps `row` in `earlier`


def _result(**kw):
    plan = {'source_id': 's1', 'post_format': {'type': 'quick_take'}, 'suggested_post_time_london': '2026-10-12T09:00',
            'angle_why': '', 'shared_event_with': [], 'same_language': True, 'title': 't'}
    return {'plan': plan, 'source': {'id': 's1'}, 'id': 'compose-r1', 'body': 'body text', 'text': 'body text',
            'draft_status': 'draft_ready', 'status': 'ok', **kw}


@pytest.mark.parametrize('extra,prefix', [
    ({'lane_fit': {'ok': False, 'detail': 'no BTC / ETH driver'}}, 'off_lane'),
    ({'arbitration': {'status': 'HOLD'}}, 'arbitration'),
    ({'stale_frame': {'code': 'stale_event_unframed'}}, 'hard: stale_event_unframed')])
@pytest.mark.parametrize('switch', ['1', '0'])
def test_compose_path_holds_through_inbox_row(monkeypatch, extra, prefix, switch):
    monkeypatch.setenv('FD_HOLD_STATUS_SYNC', switch)
    dc = _dc()
    acc = {'id': 'crypto_btc_cycle_zh', 'no': 1, 'name': 'n', 'beat': 'b', 'lang': 'zh'}
    row = dc.inbox_row(_result(**extra), acc, date(2026, 10, 12), 'RUN1')
    assert row['held'] and row['hold_reason'].startswith(prefix) and row['draft_status'] == 'draft_ready'  # the bug
    compose_inbox.add(row)
    stored = compose_inbox.get(row['id'])
    assert stored['held'] and stored['hold_reason'].startswith(prefix)
    assert stored['draft_status'] == ('needs_review' if switch == '1' else 'draft_ready')
    assert stored['publishable'] is False


# ---------------------------------------------------------------- B: no off_lane re-pick
def test_day_state_and_rules():
    rows = [_row(1, held=True, hold_reason='off_lane: a'), _row(2, held=True, hold_reason='arbitration'),
            _row(3, held=True, hold_reason='off_lane: b', account_id='other'),
            _row(4, held=True, hold_reason='off_lane: c', superseded=True)]
    st = offlane_repick.day_state(rows)
    assert offlane_repick.held_before(st, 'crypto_btc_cycle_zh', {'id': 's1'})
    assert offlane_repick.held_before(st, 'crypto_btc_cycle_zh', {'title': 'title 4'})   # by title too
    assert not offlane_repick.held_before(st, 'crypto_btc_cycle_zh', {'id': 's2'})       # arbitration != off_lane
    assert not offlane_repick.held_before(st, 'other', {'id': 's1'})                     # per account
    assert offlane_repick.blocked(st, 'crypto_btc_cycle_zh') and not offlane_repick.blocked(st, 'other')


def test_risky_uses_the_pre_pick_lane_checks(monkeypatch):
    monkeypatch.setenv('FD_LANE_FIT', '1')
    monkeypatch.setenv('FD_MACRO_LANE', '1')
    macro = {'id': 'crypto_btc_cycle_zh', 'lang': 'zh'}
    assert offlane_repick.risky(macro, 'Polymarket 巨鲸地址向币安转入 USDC')
    assert not offlane_repick.risky(macro, '比特币 ETF 净流入创新高')


def _sel(monkeypatch, pools, accounts, labels, inbox=(), risky=None):
    dc = _dc('dc_offlane_sel')
    ref = datetime(2026, 10, 12, 4, tzinfo=timezone.utc)
    for k, v in {'FD_TOPIC_DIV': '0', 'FD_HOTSPOT': '0', 'FD_SLOT_RULE': '0', 'FD_HEAT': '0', 'FD_X_BREADTH': '0',
                 'FD_LANE_FIT': '0', 'FD_TWIN_RULE': '1', 'FD_POST_KIND': '0', 'FD_DIARY_SLOT': '0'}.items():
        monkeypatch.setenv(k, v)
    for r in inbox:
        compose_inbox.add(r)
    monkeypatch.setattr(sd, 'history_rows', lambda day, **k: [])
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
                                                                 'thread_parts': 1, 'length_target': 200, 'shapes': []})
    monkeypatch.setattr(dc.ph, 'sample_post_time', lambda *a, **k: ref)
    if risky is not None:
        monkeypatch.setattr(offlane_repick, 'risky', risky)
    universes = {a['id']: {'angle_lead': {'macro_liquidity': 0.4, 'price_structure': 0.3, 'narrative_sector': 0.3},
                           'x_sources': []} for a in accounts}
    info = {}
    plan, _ = dc.select(accounts, universes, date(2026, 10, 12), 1, now=ref, info=info)
    return plan, info


def _g(i, title):
    src = {'id': f's{i}', 'source_hash': f'h{i}', 'title': title, 'publisher': f'pub{i}', 'adapter': 'rss', 'url': '',
           'published_at': datetime(2026, 10, 12, 1, tzinfo=timezone.utc).isoformat()}
    return [{'unit_id': f'u{i}', 'licence_tier': 'B', 'tag_personas': [], 'source': src,
             'unit': {'kind': 'view', 'statement': title, 'numbers': []}}]


def lab(e, a, o='', k='', b='stablecoins_tether'):
    return {'b': b, 'e': e, 'a': a, 'o': o, 'k': k}


LABELS = {'freezes': lab('Tether', 'freezes', '', 'Tether freezes USDT', b='stablecoins_tether'),
          'meme': lab('pump.fun', 'launches', '', 'pump.fun launches app', b='memecoins_launchpads')}
ACCTS = [{'id': 'crypto_meme_zh', 'lang': 'zh', 'retrieval_beats': []},
         {'id': 'crypto_stable_yield_zh', 'lang': 'zh', 'retrieval_beats': []}]


def _pools():
    return {'crypto_meme_zh': [_g(1, 'Tether freezes USDT wallets'), _g(2, 'pump.fun meme launches app')],
            'crypto_stable_yield_zh': []}


def _hold(i, account='crypto_stable_yield_zh', title=None):
    return _row(i, account_id=account, held=True, hold_reason='off_lane: no lane tie-in',
                source={'id': f's{i}', 'title': title or f'title {i}'})


@needs_mix
@pytest.mark.parametrize('switch', ['1', '0'])
def test_handover_does_not_repick_a_source_held_off_lane_today(monkeypatch, switch):
    """10-12 crypto_btc_cycle_zh: the same handed-over packet, held off_lane in every --fill round."""
    monkeypatch.setenv('FD_OFFLANE_REPICK', switch)
    plan, info = _sel(monkeypatch, _pools(), ACCTS, LABELS, inbox=[_hold(1)])
    assert plan['crypto_meme_zh'][0]['title'].startswith('pump.fun')
    if switch == '1':
        assert plan['crypto_stable_yield_zh'] == []
        assert info['offlane_repick']['skipped']['crypto_stable_yield_zh']['held_off_lane_today'] == 1
    else:   # old behaviour: handed the same packet again
        assert plan['crypto_stable_yield_zh'][0]['title'].startswith('Tether')
        assert 'offlane_repick' not in info


@needs_mix
@pytest.mark.parametrize('switch', ['1', '0'])
def test_two_offlane_holds_block_handover_picks(monkeypatch, switch):
    monkeypatch.setenv('FD_OFFLANE_REPICK', switch)
    plan, info = _sel(monkeypatch, _pools(), ACCTS, LABELS, inbox=[_hold(8), _hold(9)])   # other sources
    if switch == '1':
        assert plan['crypto_stable_yield_zh'] == []
        assert info['offlane_repick']['skipped']['crypto_stable_yield_zh'] == {'blocked_handover': 1, 'blocked_relax': 1}
    else:
        assert plan['crypto_stable_yield_zh'][0]['reassigned_from'] == 'crypto_meme_zh'


@needs_mix
@pytest.mark.parametrize('switch', ['1', '0'])
def test_blocked_account_falls_through_to_on_lane_candidate(monkeypatch, switch):
    monkeypatch.setenv('FD_OFFLANE_REPICK', switch)
    accts = [{'id': 'crypto_meme_zh', 'lang': 'zh', 'retrieval_beats': []}]
    pools = {'crypto_meme_zh': [_g(3, 'meme risky Polymarket whale'), _g(2, 'pump.fun meme launches app')]}
    plan, info = _sel(monkeypatch, pools, accts, LABELS, inbox=[_hold(8, 'crypto_meme_zh'), _hold(9, 'crypto_meme_zh')],
                      risky=lambda acc, text, own_x=False: 'risky' in text)
    want = 'pump.fun' if switch == '1' else 'meme risky'
    assert plan['crypto_meme_zh'][0]['title'].startswith(want)


@needs_mix
def test_one_offlane_hold_does_not_block_risky_picks(monkeypatch):
    accts = [{'id': 'crypto_meme_zh', 'lang': 'zh', 'retrieval_beats': []}]
    pools = {'crypto_meme_zh': [_g(3, 'meme risky Polymarket whale'), _g(2, 'pump.fun meme launches app')]}
    plan, _ = _sel(monkeypatch, pools, accts, LABELS, inbox=[_hold(8, 'crypto_meme_zh')],
                   risky=lambda acc, text, own_x=False: 'risky' in text)
    assert plan['crypto_meme_zh'][0]['title'].startswith('meme risky')


@needs_mix
def test_no_holds_today_is_a_no_op(monkeypatch):
    plan, info = _sel(monkeypatch, _pools(), ACCTS, LABELS)
    assert plan['crypto_stable_yield_zh'][0]['title'].startswith('Tether')
    assert info['offlane_repick'] == {'holds_today': {}, 'skipped': {}}
