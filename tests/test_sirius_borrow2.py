"""Oct 7 Sirius borrow items 2 + 4: sentence -> span grounding, one targeted hard rewrite then HOLD, model errors on
their own path, superseded soft-replace on reruns."""
import json
import sys
from pathlib import Path

import pytest

from live import compose_inbox, qa_levels, span_grounding as sg
from tests.test_compose import GOOD_BODY, Fake, run

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts')]

UNITS = [{'unit_id': 'u1', 'statement': 'Nvidia revenue rose',
          'source_spans': [{'exact_text': 'Nvidia said revenue rose 45.6% to $1.234 billion in Q3 2026, and CEO '
                                          'Jensen Huang said "demand is insane right now".'}]}]
SRC = {'published_at': '2026-10-07', 'original_text': 'TSMC capacity is tight.\n\nAMD was not mentioned.'}


def codes(body, units=UNITS, source=SRC):
    return {f['code'] for f in sg.findings(body, units, source)}


def test_grounded_numbers_quotes_and_rounding():
    assert codes('Nvidia revenue jumped 46% to $1.2 billion in Q3. Huang: "demand is insane right now".') == set()
    assert codes('英伟达营收增长45.6%，达到12.34亿美元。') == set()          # cross-language scale / currency
    assert codes('Three things matter. Oct 7, 2026 is the date; H1 2026 too.') == set()   # anchors, small counts
    assert codes('我觉得这轮还没完。') == set()                                 # opinion line: not checked


def test_ungrounded_number_and_quote_are_hard():
    assert codes('Revenue rose 52% to $1.5 billion.') == {'ungrounded_number'}
    assert codes('Huang said "demand is crazy everywhere today".') == {'ungrounded_quote'}
    for code in sg.HARD_CODES:
        assert qa_levels.level({'code': code}, frame_found=True) == 'hard'
        assert code in qa_levels.FIXES


def test_ungrounded_entity_and_claim_warn():
    assert codes('Intel announced a new chip.') == {'ungrounded_entity'}
    assert 'ungrounded_entity' not in codes('AMD was quiet.')                    # in the source text
    assert codes('the regulator announced a broad review of chip exports.') == {'ungrounded_claim'}
    for code in sg.SOFT_CODES:
        assert qa_levels.level({'code': code}, frame_found=True) == 'soft'


def test_map_points_each_factual_sentence_at_a_span():
    _, rows = sg.ground('Revenue rose 45.6%. I think it holds.', UNITS, SRC)
    assert rows[0]['kind'] == 'number' and rows[0]['span'] == 'u1#0'
    assert rows[1]['kind'] == 'opinion' and rows[1]['span'] is None


class Scripted(Fake):
    """First compose returns `bodies[0]`, the hard_repair rewrite `bodies[1]` (or raises)."""

    def __init__(self, bodies, error=None):
        super().__init__(body=bodies[0])
        self.bodies, self.error, self.notes = list(bodies), error, []

    def __call__(self, stage, messages, max_tokens):
        if stage == 'compose':
            payload = json.loads(messages[-1]['content'])
            note = str(payload.get('rewrite_note') or '')
            self.notes.append(note)
            if note.startswith('[hard_repair]'):
                if self.error:
                    raise RuntimeError(self.error)
                self.body = self.bodies[1]
        return super().__call__(stage, messages, max_tokens)


def test_one_targeted_rewrite_clears_the_hold():
    bad = GOOD_BODY.replace('69.5%', '72%')
    result, fake = run(Scripted([bad, GOOD_BODY]), post_type='data_take')
    hard_notes = [n for n in fake.notes if n.startswith('[hard_repair]')]
    assert len(hard_notes) == 1 and 'ungrounded_number' not in hard_notes[0] and '72%' in hard_notes[0]
    assert result['hard_repair']['result'] == 'cleared' and result['hard_repair']['kept'] == 'retry'
    assert result['draft_status'] == 'draft_ready' and result['body'] == GOOD_BODY
    assert any(r['span'] for r in result['span_grounding']['sentences'])


def test_still_hard_after_the_rewrite_is_held():
    bad = GOOD_BODY.replace('69.5%', '72%')
    result, fake = run(Scripted([bad, bad]), post_type='data_take')
    assert sum(n.startswith('[hard_repair]') for n in fake.notes) == 1      # exactly one, never a second
    assert result['hard_repair']['result'] == 'still_hard'
    assert result['draft_status'] == 'needs_review'


def test_model_error_is_a_separate_path():
    bad = GOOD_BODY.replace('69.5%', '72%')
    result, _ = run(Scripted([bad, bad], error='HTTP 400 bad request'), post_type='data_take')
    assert result['hard_repair']['result'] == 'rewrite_error' and 'HTTP 400' in result['hard_repair']['error']
    assert result['draft_status'] == 'needs_review'
    import daily_compose as dc
    row = dc.inbox_row(dict(result, plan={'post_format': {}, 'suggested_post_time_london': '', 'angle_why': '',
                                          'shared_event_with': [], 'source_id': 's'}, spend_usd=0),
                       {'id': 'zh_industry', 'no': 1, 'name': 'x', 'beat': 'b', 'lang': 'zh'}, __import__('datetime').date(2026, 10, 7), 'run')
    assert row['held'] and row['hold_reason'].startswith('model_error: ')
    assert row['hard_repair']['result'] == 'rewrite_error'


def test_draft_client_keeps_a_hard_repair_allowance():
    import daily_compose as dc

    class Inner:
        stage_models = {}
        calls = []

        def __call__(self, stage, messages, max_tokens):
            return {'response_model': 'gemini-3-flash-preview'}

    client = dc.DraftClient(Inner(), [])
    client.left['compose'] = 0                          # polish rewrites used up the compose cap
    msg = [{'role': 'user', 'content': json.dumps({'rewrite_note': '[hard_repair] fix'})}]
    assert client('compose', msg, 10)['response_model'].startswith('gemini-')
    client('compose', msg, 10)
    from ml import budget
    with pytest.raises(budget.BudgetExceeded):
        client('compose', msg, 10)
    with pytest.raises(budget.BudgetExceeded):
        client('compose', [{'role': 'user', 'content': '{}'}], 10)


def test_rerun_supersedes_instead_of_deleting(tmp_path, monkeypatch):
    import daily_compose as dc
    monkeypatch.setenv('FD_COMPOSE_INBOX', str(tmp_path))
    base = {'day': '2026-10-07', 'account_id': 'a', 'source': {'id': 's1'}}
    compose_inbox.add({**base, 'id': 'old', 'text': 'x', 'run_id': 'r1', 'held': True})
    compose_inbox.add({**base, 'id': 'ready', 'text': 'y', 'run_id': 'r1', 'held': False, 'source': {'id': 's2'}})
    compose_inbox.add({**base, 'id': 'reviewed', 'text': 'z', 'run_id': 'r0', 'review_status': 'approved'})
    earlier = compose_inbox.rows('2026-10-07')
    new = {**base, 'id': 'new', 'text': 'x2', 'run_id': 'r2', 'held': False}
    compose_inbox.add(new)
    assert dc.supersede_previous(new, earlier) == ['old']
    old = compose_inbox.get('old')
    assert old['superseded'] and old['superseded_by'] == 'new' and old['superseded_reason'] == 'rerun'
    assert not compose_inbox.get('reviewed').get('superseded')          # human-reviewed drafts untouched
    held_rerun = {**base, 'id': 'new2', 'text': 'y2', 'run_id': 'r3', 'held': True, 'source': {'id': 's2'}}
    assert dc.supersede_previous(held_rerun, compose_inbox.rows('2026-10-07')) == []   # a HOLD never replaces ready
    rewrite = {**base, 'id': 'new3', 'text': 'y3', 'run_id': 'r4', 'held': True, 'rewrite_of': 'ready',
               'source': {'id': 's9'}}
    assert dc.supersede_previous(rewrite, compose_inbox.rows('2026-10-07')) == ['ready']
    assert len(list((tmp_path / '2026-10-07').glob('*.json'))) == 4      # old / ready / reviewed / new: nothing deleted
