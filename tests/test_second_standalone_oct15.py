"""Oct 15 (Fiona; FD_SECOND_STANDALONE, default on): an account with 1 standalone ready and NO engagement target may
take a 2nd original standalone; with an engagement row / live target the slot rule is unchanged; switch off == old."""
import pytest

from tests.test_archive_fallback_oct12 import ACCT, _env, _eng, _fresh, _g, _sel  # noqa: F401


def _ids(plan):
    return [p.get('source_id') for p in plan[ACCT]]


def test_second_standalone_without_engage_target(monkeypatch):
    pools = {ACCT: [_g(1, 'Alpha news one'), _g(2, 'Zeta other story two')]}
    _dc, plan, _ = _sel(monkeypatch, pools, inbox=[_fresh(9)], done={ACCT: 1})
    assert len(plan[ACCT]) == 1 and plan[ACCT][0]['source_id'] in ('s1', 's2')


def test_switch_off_keeps_one_standalone(monkeypatch):
    monkeypatch.setenv('FD_SECOND_STANDALONE', '0')
    pools = {ACCT: [_g(1, 'Alpha news one'), _g(2, 'Zeta other story two')]}
    _dc, plan, _ = _sel(monkeypatch, pools, inbox=[_fresh(9)], done={ACCT: 1})
    assert plan[ACCT] == []


def test_engage_row_today_blocks_second_standalone(monkeypatch):
    pools = {ACCT: [_g(1, 'Alpha news one')]}
    _dc, plan, _ = _sel(monkeypatch, pools, inbox=[_fresh(9), _eng(8)], done={ACCT: 2})
    assert plan[ACCT] == []


def test_live_engage_target_in_pool_blocks_second_standalone(monkeypatch):
    pools = {ACCT: [_g(1, 'Alpha news one'), _g(2, 'Beta news two', sid='x-1234567')]}
    _dc, plan, _ = _sel(monkeypatch, pools, inbox=[_fresh(9)], done={ACCT: 1})
    assert plan[ACCT] == []
