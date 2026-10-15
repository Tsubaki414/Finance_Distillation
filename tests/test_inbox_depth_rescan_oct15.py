"""Oct 15 scripts/inbox_depth_rescan.py: re-run calibrated depth_check on stored held rows; flip only depth-only holds
the calibration now passes. Synthetic fixtures only (no live donor / tweet / article text)."""
import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('inbox_depth_rescan', ROOT / 'scripts' / 'inbox_depth_rescan.py')
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)

DAY = '2026-10-15'
# grounded figure + own judgment line: held by the Oct 13 rule, passes with FD_DEPTH_HOLD_CAL
PASS_BODY = ('ChartGuy notes that SOL is sitting on its $142 support zone.\n\n'
             'Losing it leaves the door open to $128 before anyone gets a real bounce.')
PASS_SRC = '$SOL is now at its $142 support zone.'
# facts only: still held
HOLD_BODY = 'Treasury firm bought 2,100 BTC last week. It now holds 31,500 coins.'
HOLD_SRC = 'Treasury firm adds 2,100 BTC, holdings rise to 31,500'


def row(rid, body, src, hold_reason='hard: depth', extra_findings=(), **kw):
    r = {'id': rid, 'day': DAY, 'account_id': 'acct_' + rid, 'lang': 'en', 'post_type': 'judgment_take',
         'post_kind': None, 'body': body, 'text': body, 'source': {'title': src}, 'held': True,
         'draft_status': 'needs_review', 'hold_reason': hold_reason, 'review_status': 'pending',
         'publishable': False, 'arbitration': {},
         'findings': [{'code': 'emotion_drop', 'level': 'soft'}, *extra_findings, {'code': 'depth', 'level': 'hard'}]}
    r.update(kw)
    return r


@pytest.fixture
def inbox(tmp_path):
    base, backup = tmp_path / 'inbox', tmp_path / 'backup'
    (base / DAY).mkdir(parents=True)
    rows = [
        row('flip', PASS_BODY, PASS_SRC),
        row('flipme', PASS_BODY, PASS_SRC, hold_reason='model_error: depth'),
        row('still', HOLD_BODY, HOLD_SRC),
        row('other', PASS_BODY, PASS_SRC, hold_reason='hard: depth,jargon_unexplained',
            extra_findings=[{'code': 'jargon_unexplained', 'level': 'hard'}]),
        row('otherf', PASS_BODY, PASS_SRC, extra_findings=[{'code': 'ungrounded_number', 'level': 'hard'}]),
        row('arb', PASS_BODY, PASS_SRC, arbitration={'status': 'HOLD'}),
        row('sup', PASS_BODY, PASS_SRC, superseded=True),
        row('reviewed', PASS_BODY, PASS_SRC, review_status='rejected'),
        {'id': 'ready', 'day': DAY, 'account_id': 'a', 'lang': 'en', 'body': PASS_BODY, 'held': False,
         'draft_status': 'draft_ready', 'hold_reason': None, 'findings': []},
    ]
    for r in rows:
        (base / DAY / f"{r['id']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2) + '\n')
    return base, backup


def snapshot(base):
    return {p.name: p.read_bytes() for p in (base / DAY).glob('*.json')}


def verdicts(res):
    return {i['id']: i['verdict'] for i in res['rows']}


def test_dry_run_default_classifies_and_writes_nothing(inbox):
    base, backup = inbox
    before = snapshot(base)
    res = rs.run(DAY, base, backup, env={})
    assert res['mode'] == 'dry_run'
    assert verdicts(res) == {'flip': 'flip', 'flipme': 'flip', 'still': 'stay_held', 'other': 'other_hard',
                             'otherf': 'other_hard', 'arb': 'other_hard', 'sup': 'not_candidate',
                             'reviewed': 'not_candidate'}
    assert snapshot(base) == before and not backup.exists()


def test_apply_flips_only_depth_only_rows_and_backs_up(inbox):
    base, backup = inbox
    before = snapshot(base)
    res = rs.run(DAY, base, backup, env={}, apply=True)
    assert res['mode'] == 'apply'
    assert sorted(i['id'] for i in res['rows'] if i['written']) == ['flip', 'flipme']
    after = snapshot(base)
    assert {n for n in after if after[n] != before[n]} == {'flip.json', 'flipme.json'}
    for rid in ('flip', 'flipme'):
        assert (backup / DAY / f'{rid}.json').read_bytes() == before[f'{rid}.json']
        r = json.loads(after[f'{rid}.json'])
        assert r['held'] is False and r['draft_status'] == 'draft_ready' and r['hold_reason'] is None
        assert r['publishable'] is False and r['review_status'] == 'pending'
        assert [f['code'] for f in r['findings']] == ['emotion_drop']
        assert r['depth_rescan']['old_hold_reason'] in ('hard: depth', 'model_error: depth')
        assert r['body'] == PASS_BODY
    assert sorted(p.name for p in (backup / DAY).iterdir()) == ['flip.json', 'flipme.json']


def test_rerun_keeps_first_backup(inbox):
    base, backup = inbox
    orig = (base / DAY / 'flip.json').read_bytes()
    rs.run(DAY, base, backup, env={}, apply=True)
    res = rs.run(DAY, base, backup, env={}, apply=True)
    assert 'flip' not in verdicts(res)            # already ready: no hard depth left
    assert (backup / DAY / 'flip.json').read_bytes() == orig


def test_kill_switch_forces_dry_run(inbox):
    base, backup = inbox
    before = snapshot(base)
    res = rs.run(DAY, base, backup, env={'FD_INBOX_DEPTH_RESCAN': '0'}, apply=True)
    assert res['mode'] == 'dry_run' and snapshot(base) == before and not backup.exists()


def test_apply_env_flag():
    assert rs.apply_requested(env={}) is False
    assert rs.apply_requested(env={'APPLY': '1'}) is True
    assert rs.apply_requested(env={'APPLY': '0'}) is False
    assert rs.apply_requested(env={}, flag=True) is True


def test_refuses_when_depth_check_or_cal_off(inbox):
    base, backup = inbox
    for env in ({'FD_DEPTH_CHECK': '0'}, {'FD_DEPTH_HOLD_CAL': '0'}):
        with pytest.raises(SystemExit):
            rs.run(DAY, base, backup, env=env, apply=True)


def test_cli_without_apply_is_dry(inbox, monkeypatch, tmp_path):
    base, backup = inbox
    monkeypatch.delenv('APPLY', raising=False)
    monkeypatch.delenv('FD_INBOX_DEPTH_RESCAN', raising=False)
    before = snapshot(base)
    out = tmp_path / 'r.json'
    res = rs.main([DAY, '--base', str(base), '--backup', str(backup), '--json', str(out)])
    assert res[0]['mode'] == 'dry_run' and snapshot(base) == before
    assert json.loads(out.read_text())[0]['tally']['flip'] == 2
