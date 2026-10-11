"""Oct 11 quality_rootcause_1011 fixes: event fact, post-edit guard, final QA, freshness gate, midday relay mapping."""
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from live import rc_guard as g

ROOT = Path(__file__).resolve().parents[1]


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, stage, messages, max_tokens):
        self.calls.append((stage, messages[-1]['content']))
        a = self.answers.pop(0) if self.answers else {}
        return {'text': json.dumps(a, ensure_ascii=False)}


# ---------------------------------------------------------------- edit guard
def test_number_dropped_zh_glued_number():
    # humanize._values misses 「达到6%」 (CJK char + digit); the guard does not (10-10 墨川 "6%" -> "极高水平")
    assert any(r.startswith('number_dropped') for r in g.edit_check('收益率达到6%，风险不小', '收益率处在极高水平，风险不小'))


def test_rounding_and_closer_cut_kept():
    assert g.edit_check('冻结了276万美元', '冻结了约280万美元') == []
    assert g.edit_check('BTC 跌到 82,000', 'BTC 跌到 8.2万') == []
    assert g.edit_check('BTC 跌到 82,000。\n说到底还是流动性。', 'BTC 跌到 82,000') == []


def test_event_and_caveat_dropped():
    ev = {'event': 'Bukele denied the Bloomberg report on 2026-10-07'}
    before = 'Bukele denied the Bloomberg stablecoin story.\nStill watching.'
    assert any(r.startswith('event_dropped') for r in g.edit_check(before, 'El Salvador is launching a stablecoin.', ev))
    assert 'caveat_dropped' in g.edit_check('据报道 X 将上线', 'X 将上线')


def test_invented_first_person():
    out = g.edit_check('Following the cut, BTC rallied 4%.', 'Following the cut, BTC rallied 4%. I saw this before.')
    assert any(r.startswith('invented_first_person') for r in out)
    assert any(r.startswith('invented_first_person') for r in g.edit_check('流动性在收紧', '我复盘了下，流动性在收紧'))


def test_guard_step_reverts_and_logs(monkeypatch):
    row = {'account_id': 'a', 'body': '收益率处在极高水平', 'text': '收益率处在极高水平'}
    assert g.guard_step(row, 'humanize', '收益率达到6%') is True
    assert row['body'] == '收益率达到6%' and row['text'] == '收益率达到6%'
    e = row['edit_guard'][0]
    assert e['before'] == '收益率达到6%' and e['after'] == '收益率处在极高水平' and e['reverted']


def test_guard_step_llm_flip_and_switch(monkeypatch):
    row = {'account_id': 'a', 'body': 'Only if the cut holds, BTC rallies.'}
    c = FakeClient([{'damaged': True, 'kind': 'flip', 'why': 'condition added'}])
    assert g.guard_step(row, 'hook_rewrite', 'Following the cut, BTC rallies.', client=c, llm=True)
    monkeypatch.setenv('FD_EDIT_GUARD', '0')
    row = {'body': 'x2'}
    assert g.guard_step(row, 'humanize', 'x 6%') is False and row['body'] == 'x2'


# ---------------------------------------------------------------- truncation
@pytest.mark.parametrize('body,bad', [
    ('The market is pricing in a cut and', True),
    ('利率下行，因为', True),
    ('（这里没收尾', True),
    ('能在美国提供事件合约与加密衍生品交易服务', False),   # no final period = donor habit
    ('BTC holds 82k\nwatching the close', False),
])
def test_broken_text(body, bad):
    assert bool(g.broken_text(body)) is bad


# ---------------------------------------------------------------- event fact
def test_stored_event_wins_and_derive(monkeypatch):
    units = [{'statement': 'bg', 'kind': 'fact'}, {'statement': 'Tether sued 10-05', 'lead_event': True, 'event_date': '2026-10-05'}]
    assert g.derive_event({'original_text': 'x' * 50}, units, None, 'en')['from'] == 'extract'
    c = FakeClient([{'event': 'A lawsuit was filed against Tether in Manhattan on 2026-10-05', 'when': '2026-10-05'}])
    ev = g.derive_event({'original_text': 'Tether faces a lawsuit filed Oct 5 in Manhattan ...', 'published_at': '2026-10-06'},
                        [], c, 'en')
    assert ev['from'] == 'derive' and '2026-10-05' in ev['event'] and c.calls[0][0] == 'stance'
    assert g.payload_block(ev)['rule'].startswith('HARD')
    monkeypatch.setenv('FD_EVENT_FACT', '0')
    assert g.derive_event({'original_text': 'x' * 50}, units, c, 'en') is None


def test_event_prompt_and_unit_fields(monkeypatch):
    from live import flash_extract, prompt_assembly
    monkeypatch.setenv('FD_EVENT_FACT_EXTRACT', '1')   # default ON in runs, OFF under pytest (recorded prompts)
    t = g.event_prompt(flash_extract.FLASH_EXTRACT)
    assert t.endswith(g.EVENT_ADDENDUM) and prompt_assembly.template_id(t) == 'flash_units.EXTRACT+event'
    assert g.lead_event_fields({'kind': 'fact', 'lead_event': True, 'event_date': '2026-10-05'}) == \
        {'lead_event': True, 'event_date': '2026-10-05'}
    assert g.lead_event_fields({'kind': 'view', 'lead_event': True}) == {}
    monkeypatch.setenv('FD_EVENT_FACT', '0')
    assert g.event_prompt(flash_extract.FLASH_EXTRACT) == flash_extract.FLASH_EXTRACT


def test_compose_source_takes_event_fact():
    from live import compose
    assert 'event_fact' in inspect.signature(compose.compose_source).parameters


# ---------------------------------------------------------------- final QA
SRC = {'title': 'El Salvador denies stablecoin report', 'published_at': '2026-10-07T10:00:00Z',
       'original_text': 'Bukele and the National Bitcoin Office denied the Bloomberg report on a stablecoin platform.'}
EV = {'event': 'Bukele denied the Bloomberg report on 2026-10-07'}


def test_final_pass():
    row = {'account_id': 'a', 'body': 'Bukele denied the Bloomberg stablecoin report.', 'source': SRC, 'event_fact': EV}
    rec = g.final_check(row, FakeClient([{'event_stated': True, 'fact_errors': [], 'broken': False}]))
    assert rec['result'] == 'pass' and 'draft_status' not in row


def test_final_rewrite_fixes():
    row = {'account_id': 'a', 'body': 'El Salvador is launching a stablecoin.', 'text': 'El Salvador is launching a stablecoin.',
           'source': SRC, 'event_fact': EV}
    c = FakeClient([{'event_stated': False, 'fact_errors': ['states the denied report as fact'], 'broken': False},
                    {'body': 'Bukele denied the Bloomberg report that El Salvador is launching a stablecoin.'},
                    {'event_stated': True, 'fact_errors': [], 'broken': False}])
    rec = g.final_check(row, c)
    assert rec['result'] == 'rewritten' and row['body'].startswith('Bukele denied') and row['text'] == row['body']
    assert rec['rewrite']['before'] == 'El Salvador is launching a stablecoin.'


def test_final_hold_after_one_rewrite(monkeypatch):
    row = {'account_id': 'a', 'body': 'El Salvador is launching a stablecoin.', 'source': SRC, 'event_fact': EV}
    bad = {'event_stated': False, 'fact_errors': [], 'broken': False}
    c = FakeClient([bad, {'body': 'El Salvador has a new coin.'}, bad])
    rec = g.final_check(row, c)
    assert rec['result'] == 'hold' and row['draft_status'] == 'needs_review'
    assert {'code': 'event_missing', 'level': 'hard'}.items() <= row['post_checks'][0].items()
    assert len(c.calls) == 3   # check, ONE rewrite, re-check


def test_final_truncation_without_judge():
    row = {'account_id': 'a', 'body': 'The market is pricing in a cut and', 'source': SRC}
    c = FakeClient([{}, {}, {}])   # judge returns nothing usable / rewrite empty
    rec = g.final_check(row, c)
    assert rec['result'] == 'hold' and 'broken_text' in rec['codes']


def test_final_switches(monkeypatch):
    monkeypatch.setenv('FD_RC_QA_HOLD', '0')
    row = {'account_id': 'a', 'body': 'El Salvador is launching a stablecoin.', 'source': SRC, 'event_fact': EV}
    bad = {'event_stated': False, 'fact_errors': [], 'broken': False}
    rec = g.final_check(row, FakeClient([bad, {}, bad]))
    assert rec['result'] == 'hold' and 'draft_status' not in row
    monkeypatch.setenv('FD_RC_QA', '0')
    rows = [{'body': 'x', 'source': SRC}]
    g.final_batch(rows, lambda: FakeClient([]))
    assert 'rc_qa' not in rows[0]


# ---------------------------------------------------------------- freshness gate
def _grp(hours, ref):
    return [{'source': {'published_at': (ref - timedelta(hours=hours)).isoformat(), 'id': f's{hours}'}}]


def test_fresh_gate(monkeypatch):
    import scripts.daily_compose as dc
    ref = datetime(2026, 10, 11, 22, 15, tzinfo=timezone.utc)
    pools = {'a': [_grp(10, ref), _grp(39, ref), _grp(45, ref), _grp(173, ref), [{'source': {'published_at': None}}]]}
    info = {}
    dc.fresh_gate(pools, ref, info)
    assert [g_[0]['source'].get('id') for g_ in pools['a']] == ['s10', 's39', None]
    assert info['fresh_gate']['dropped'] == {'a': 2} and info['fresh_gate']['undated_kept'] == {'a': 1}
    assert dc.fresh_pref(_grp(30, ref), ref) is True and dc.fresh_pref(_grp(20, ref), ref) is False
    pools = {'a': [_grp(173, ref)]}
    dc.fresh_gate(pools, ref, None, env={'FD_FRESH_GATE': '0'})
    assert len(pools['a']) == 1


def test_noop_retry_switch(monkeypatch):
    src = (ROOT / 'live' / 'compose.py').read_text(encoding='utf-8')
    assert "_dnr()" in src and "'dropped_noop_retry'" in src
    assert g.drop_noop_retry({}) is True                       # a run: default ON
    assert g.drop_noop_retry({'PYTEST_CURRENT_TEST': 'x'}) is False
    assert g.drop_noop_retry({'FD_RC_DROP_NOOP_RETRY': '0'}) is False


def test_midday_maps_relay_key():
    sh = (ROOT / 'scripts' / 'cron' / 'midday_compose.sh').read_text(encoding='utf-8')
    i_map, i_ingest = sh.index('export ACCOUNT_RELAY_API_KEY='), sh.index('scripts/daily_ingest.py')
    assert i_map < i_ingest and 'FD_MIDDAY_RELAY_MAP' in sh


# ---------------------------------------------------------------- freshness look-back fallback
def test_fresh_gate_lookback_fallback():
    import scripts.daily_compose as dc
    ref = datetime(2026, 10, 11, 22, 15, tzinfo=timezone.utc)
    dc.LOOKBACK_PICKS.clear()
    pools = {'a': [_grp(100, ref), _grp(60, ref), _grp(80, ref), _grp(200, ref)], 'b': [_grp(10, ref), _grp(60, ref)]}
    info = {}
    dc.fresh_gate(pools, ref, info, env={})
    assert [x[0]['source']['id'] for x in pools['a']] == ['s60', 's80']   # youngest 2 expired, <= 120 h at the slot
    assert [x[0]['source']['id'] for x in pools['b']] == ['s10']          # has a fresh item: no fallback
    assert info['fresh_gate']['lookback_kept_age_h'] == {'a': [68.0, 88.0]}
    assert len(dc.LOOKBACK_PICKS) == 2
    pools = {'a': [_grp(60, ref)]}
    dc.fresh_gate(pools, ref, None, env={'FD_FRESH_LOOKBACK': '0'})
    assert pools['a'] == []
    dc.LOOKBACK_PICKS.clear()


def test_lookback_payload_and_findings():
    ev = {'event': 'Tether froze $2.76m', 'frame': 'lookback', 'age_h': 96}
    blk = g.payload_block(ev)
    assert 'frame_rule' in blk and '4 days' in blk['frame_rule'] and blk['event'] == 'Tether froze $2.76m'
    assert 'frame_rule' in g.payload_block({'frame': 'lookback', 'age_h': 60})
    assert g.payload_block({'event': 'x'}).get('frame_rule') is None
    assert g.lookback_findings('Tether froze $2.76m.', ev)
    assert g.lookback_findings('回看上周：Tether 冻结了276万美元，现在稳定币发行方的权力更清楚了。', ev) == []
    assert g.lookback_findings('Tether froze $2.76m.', {'event': 'x'}) == []


def test_final_check_lookback_rewrite_then_hold(monkeypatch):
    monkeypatch.setenv('FD_RC_QA_HOLD', '1')
    ok = {'event_stated': True, 'fact_errors': [], 'broken': False}
    ev = {'event': 'Tether froze $2.76m', 'frame': 'lookback', 'age_h': 96}
    row = {'account_id': 'a', 'body': 'Tether froze $2.76m.', 'event_fact': ev, 'source': {'title': 't'}}
    rec = g.final_check(row, FakeClient([ok, {'body': 'Tether froze $2.76m again.'}, ok]))
    assert rec['result'] == 'hold' and 'lookback_unframed' in rec['codes']
    row = {'account_id': 'a', 'body': 'Tether froze $2.76m.', 'event_fact': ev, 'source': {'title': 't'}}
    rec = g.final_check(row, FakeClient([ok, {'body': 'Looking back at last week: Tether froze $2.76m. Now issuers matter more.'}, ok]))
    assert rec['result'] == 'rewritten' and row['body'].startswith('Looking back')


def test_final_human_kind_needs_no_event_but_facts_still_hold():
    """Oct 11 eve: a diary / reaction only needs the event as a backdrop; a wrong fact still fails and its rewrite
    removes rather than adds data."""
    row = {'account_id': 'a', 'body': 'told myself no charts today. lasted ten minutes', 'source': SRC, 'event_fact': EV,
           'plan': {'post_format': {'kind': 'diary'}}}
    c = FakeClient([{'event_stated': False, 'fact_errors': [], 'broken': False}])
    rec = g.final_check(row, c)
    assert rec['result'] == 'pass' and rec['event_relaxed'] == 'diary' and len(c.calls) == 1
    row = {'account_id': 'a', 'body': 'El Salvador is launching a stablecoin and I am tired.', 'source': SRC, 'event_fact': EV,
           'plan': {'post_format': {'kind': 'reaction'}}}
    bad = {'event_stated': False, 'fact_errors': ['states the denied report as fact'], 'broken': False}
    c = FakeClient([bad, {'body': 'stablecoin rumours again and I am tired.'}, {'event_stated': False, 'fact_errors': [], 'broken': False}])
    rec = g.final_check(row, c)
    assert rec['result'] == 'rewritten' and 'KIND reaction' in str(c.calls[1])
    assert g.human_kind({'plan': {'post_format': {'kind': 'data'}}}) is None
