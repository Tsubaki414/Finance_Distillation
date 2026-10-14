"""Oct 14: thin-lane newsletter channels win extract slots (FD_THIN_EXTRACT_PRI, live/ingest_priority.py)."""
from live import ingest_priority as ip

FRESH = {'macro_rates_en': 180, 'crypto_macro_zh': 560, 'industry_ai_capex': 250,
         'single_stock_deepdive_en': 300, 'crypto_stable_yield': 5, 'crypto_airdrop': 9,
         'crypto_defi': 120, 'crypto_meme': 150}


def _task(cid, sid, rank):
    return ({'id': cid}, {'id': sid, 'source_id': cid.split(':', 1)[-1]}, None, 'feed', [sid], rank)


def _fixture():
    """Old channel set (news desk + standard newsletters) plus two thin-lane items gathered last."""
    tasks = [_task('ch040', 'fed-1', 0), _task('ch040', 'fed-2', 1),
             _task('newsletters:old_a', 'a-1', 0), _task('newsletters:old_a', 'a-2', 1),
             _task('newsletters:old_b', 'b-1', 0), _task('newsletters:old_b', 'b-2', 1),
             _task('newsletters:old_c', 'c-1', 0), _task('newsletters:old_c', 'c-2', 1),
             _task('newsletters:thin_stablecoin_insider', 'thin-s-1', 0),
             _task('newsletters:thin_airdropalert', 'thin-a-1', 0)]
    hints = {'ch040': ['macro_rates_en'], 'newsletters:old_a': ['industry_ai_capex'],
             'newsletters:old_b': ['single_stock_deepdive_en'], 'newsletters:old_c': ['crypto_macro_zh']}
    return tasks, hints


def _order(monkeypatch, on, *, deferred=(), fit=4):
    tasks, hints = _fixture()
    monkeypatch.setattr(ip, '_hint_table', lambda: hints)
    monkeypatch.setattr(ip, '_store_personas', lambda store=None: {})
    if on:
        monkeypatch.delenv('FD_THIN_EXTRACT_PRI', raising=False)
    else:
        monkeypatch.setenv('FD_THIN_EXTRACT_PRI', '0')
    order, plan = ip.order_tasks(tasks, FRESH, deferred, floor=1, fit=fit)
    return [t[1]['id'] for t in order], plan


# HEAD (30f6921) order for this fixture: thin items unmapped + standard -> the very back of 'rest'.
BASELINE = ['fed-1', 'c-1', 'a-1', 'b-1', 'fed-2', 'a-2', 'b-2', 'c-2', 'thin-s-1', 'thin-a-1']


def test_switch_off_matches_head_order(monkeypatch):
    ids, plan = _order(monkeypatch, on=False)
    assert ids == BASELINE
    assert {r['persona'] for r in plan if r['id'].startswith('thin')} == {ip.UNKNOWN}
    assert {r['timeliness'] for r in plan if r['id'].startswith('thin')} == {'standard'}


def test_switch_on_thin_inside_first_fit_paid_slots(monkeypatch):
    fit = 4
    ids, plan = _order(monkeypatch, on=True, fit=fit)
    window = ids[:fit]
    assert any(i.startswith('thin') for i in window), ids
    # short-on-fresh thin persona goes first in the timely round-robin
    assert ids[0] == 'thin-s-1'
    rows = {r['id']: r for r in plan}
    assert rows['thin-s-1']['persona'] == 'crypto_stable_yield' and rows['thin-s-1']['timeliness'] == 'timely'
    assert rows['thin-a-1']['persona'] == 'crypto_airdrop'
    # without the persona_minimum window (fit=None) the non-thin items keep their switch-off relative order
    on, _ = _order(monkeypatch, on=True, fit=None)
    off, _ = _order(monkeypatch, on=False, fit=None)
    assert [i for i in on if not i.startswith('thin')] == [i for i in off if not i.startswith('thin')]
    assert on[:2] == ['thin-s-1', 'thin-a-1'] and off[-2:] == ['thin-s-1', 'thin-a-1']


def test_prior_deferred_thin_first_inside_its_persona(monkeypatch):
    tasks, hints = _fixture()
    tasks.insert(8, _task('newsletters:thin_stablecoin_insider', 'thin-s-0', 0))
    monkeypatch.setattr(ip, '_hint_table', lambda: hints)
    monkeypatch.setattr(ip, '_store_personas', lambda store=None: {})
    monkeypatch.delenv('FD_THIN_EXTRACT_PRI', raising=False)
    order, plan = ip.order_tasks(tasks, FRESH, {'thin-s-1'}, floor=1, fit=4)
    ids = [t[1]['id'] for t in order]
    assert ids.index('thin-s-1') < ids.index('thin-s-0')
    assert ids[0] == 'thin-s-1'


def test_thin_detection_and_routes(monkeypatch):
    monkeypatch.delenv('FD_THIN_EXTRACT_PRI', raising=False)
    assert ip.is_thin('newsletters:thin_klement')
    assert ip.is_thin('feed:x', {'source_id': 'thin_unchained'})
    assert not ip.is_thin('newsletters:themarginalist')
    assert ip.channel_personas('newsletters:thin_klement') == ['investing_philosophy']
    assert ip.channel_personas('newsletters:thin_beincrypto_trading') == ['crypto_perp', 'trading_shortterm']
    assert ip.timeliness('newsletters:thin_humbledollar') == 'timely'
    # earnings-call titles stay transcripts even on a thin feed
    assert ip.timeliness('newsletters:thin_klement', {'title': 'Q3 earnings call transcript'}) == 'transcript'
    monkeypatch.setenv('FD_THIN_EXTRACT_PRI', '0')
    assert not ip.is_thin('newsletters:thin_klement')
    assert ip.timeliness('newsletters:thin_humbledollar') == 'standard'
