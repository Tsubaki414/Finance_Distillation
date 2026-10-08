"""Feedback loop v2 (PM item 5): 已发 flag kept from the API to feedback_priors, outcome classes, stats, soft priors."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from live import feedback as fb  # noqa: E402
import apply_admin_decisions as apply  # noqa: E402
import build_admin_console as admin  # noqa: E402

NOW = datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)   # Beijing 10-09 08:00: 10-08 is a closed day


def row(i, acct='a1', angle='flows_etf', status='draft_ready', **kw):
    return {'id': i, 'account_id': acct, 'angle': {'id': angle}, 'body': f'draft {i}\nline two', 'status': status,
            'held': status == 'HOLD', 'post_type': 'judgment_take', 'post_format': {'type': 'one_liner'}, **kw}


# ------------------------------------------------------------------ hop 1: apply_admin_decisions.clean

def test_clean_keeps_published_flag_before_publish_and_text():
    blob = {'id': 'd1', 'account_id': 'a1', 'action': 'approve', 'text': ' edited ', 'published': True,
            'before_publish': 'approve', 'at': '2026-10-07T10:00:00Z', 'history': [{'action': 'published'}]}
    c = apply.clean(blob)
    assert c['published'] is True and c['before_publish'] == 'approve' and c['text'] == 'edited'
    assert apply.is_published(c) and fb.is_published(c)
    legacy = apply.clean({'id': 'd2', 'action': 'published'})   # blob written before the flag existed
    assert legacy['published'] is None and apply.is_published(legacy)
    off = apply.clean({'id': 'd3', 'action': 'approve', 'published': False, 'before_publish': 'bogus'})
    assert off['before_publish'] is None and not apply.is_published(off)


def test_merge_refreshes_a_stale_flagless_copy_with_the_same_at():
    into = {'d1': apply.clean({'id': 'd1', 'action': 'approve', 'at': 't1'})}   # pulled by the old clean()
    apply.merge(into, {'d1': {'id': 'd1', 'action': 'approve', 'published': True, 'before_publish': 'approve',
                              'at': 't1'}})
    assert into['d1']['published'] is True


# ------------------------------------------------------------------ hop 2: outcome classes

@pytest.mark.parametrize('r, d, posted, closed, want', [
    (row('1'), {'action': 'published', 'published': True}, True, True, 'published_asis'),
    (row('1'), {'action': 'published'}, True, True, 'published_asis'),                      # legacy blob
    (row('1'), {'action': 'approve', 'published': True, 'text': 'new'}, True, True, 'published_edited'),
    (row('1'), {'action': 'published', 'published': True, 'text': 'draft 1\nline two'}, True, True, 'published_asis'),
    (row('1'), {'action': 'approve', 'published': False}, True, True, 'approved'),          # unpublished again
    (row('1'), {'action': 'approve'}, False, True, 'approved'),
    (row('1'), {'action': 'hold', 'note': 'x'}, False, True, 'held'),
    (row('1'), {'action': 'rewrite'}, False, True, 'held'),
    (row('1'), {'action': 'hold', 'published': True}, True, True, 'published_asis'),        # posted anyway
    (row('1', review_status='rejected'), None, False, True, 'rejected'),
    (row('1', review_status='edited', reviewed_text='inbox edit'), None, False, True, 'approved'),
    (row('1'), {'action': 'edit', 'text': 'x'}, False, True, 'edit_only'),
    (row('1'), None, True, True, 'unpicked'),
    (row('1'), None, True, False, 'none'),                                                  # day still open
    (row('1'), None, False, True, 'none'),                                                  # account posted nothing
    (row('1', status='HOLD'), None, True, True, 'none'),                                    # ops never saw it ready
    (row('1'), {'action': 'clear'}, True, True, 'unpicked'),
])
def test_outcome_matrix(r, d, posted, closed, want):
    assert fb.outcome(r, d, posted, closed) == want


def test_media_and_hold_reason_keys():
    assert fb.media_of({'media_plan': {'status': 'made', 'style': 'tv_widget'}, 'media': [{}]}) == 'tv_widget'
    assert fb.media_of({'media_plan': {'status': 'made', 'wanted': 'candle'}, 'media': [{'chart_type': 'candle'}]}) == 'chart:candle'
    assert fb.media_of({'post_mode': 'quote'}) == 'quote' and fb.media_of({}) == 'none'
    assert fb.hold_reason_key('喊单：「少在短线里来回折腾」') == '喊单'
    assert fb.hold_reason_key('同号同事件重复（墨川已放 97df）') == '同号同事件重复'
    assert fb.hold_reason_key('hard: jargon_unexplained, x_y') == 'hard: jargon_unexplained, x_y'
    assert fb.hold_reason_key('needs light edit: Elias 周期号写') == 'needs light edit'


# ------------------------------------------------------------------ hop 3: priors + stats

def _store(tmp_path, days):
    for day, rows, dec in days:
        (tmp_path / 'inbox' / day).mkdir(parents=True, exist_ok=True)
        for r in rows:
            (tmp_path / 'inbox' / day / f"{r['id']}.json").write_text(json.dumps({**r, 'day': day}))
        (tmp_path / 'dec').mkdir(exist_ok=True)
        (tmp_path / 'dec' / f'{day}.json').write_text(json.dumps({'day': day, 'decisions': dec}))


def _decided(n_pub, n_hold, acct='a1'):
    rows, dec = [], {}
    for i in range(n_pub):
        rows.append(row(f'{acct}p{i}', acct, 'flows_etf'))
        dec[f'{acct}p{i}'] = {'id': f'{acct}p{i}', 'action': 'published', 'published': True}
    for i in range(n_hold):
        rows.append(row(f'{acct}h{i}', acct, 'price_structure', media_plan={'status': 'made', 'style': 'lw_render'},
                        media=[{}]))
        dec[f'{acct}h{i}'] = {'id': f'{acct}h{i}', 'action': 'hold', 'note': f'数据过时：「原文 {i}」'}
    return rows, dec


def test_v2_minimum_sample_then_bounded_soft_prior(tmp_path):
    rows, dec = _decided(2, 2)                       # 4 scored drafts < MIN_ACCOUNT_N
    _store(tmp_path, [('2026-10-07', rows, dec)])
    res = fb.build_v2(fb.classify(fb.collect_days(tmp_path / 'dec', tmp_path / 'inbox'), now=NOW))
    assert fb.multiplier(res['priors'], 'a1', 'angle', 'flows_etf') == 1.0
    rows, dec = _decided(4, 4)                       # 8 scored, 4 per angle
    _store(tmp_path, [('2026-10-08', rows, dec)])
    res = fb.build_v2(fb.classify(fb.collect_days(tmp_path / 'dec', tmp_path / 'inbox'), now=NOW))
    up = fb.multiplier(res['priors'], 'a1', 'angle', 'flows_etf')
    down = fb.multiplier(res['priors'], 'a1', 'media', 'lw_render')
    assert 1.0 < up <= 1 + fb.MAX_SHIFT and 1 - fb.MAX_SHIFT <= down < 1.0
    assert fb.angle_multiplier(res['priors'], 'a1', 'price_structure') == down
    s = res['stats']
    assert s['totals']['published'] == 6 and s['totals']['held'] == 6 and s['totals']['hold_rate'] == 0.5
    assert s['by']['media']['lw_render']['held'] == 6 and s['hold_reasons']['review'] == [('HOLD：数据过时', 6)]


def test_v2_write_keeps_text_local_and_stats_text_free(tmp_path):
    rows = [row('e1'), row('e2'), row('e3'), row('u1', 'a2'), row('u2', 'a2')]
    dec = {'e1': {'id': 'e1', 'action': 'approve', 'published': True, 'text': 'SECRET edited body'},
           'e2': {'id': 'e2', 'action': 'approve', 'text': 'ANOTHER edit'},
           'u1': {'id': 'u1', 'action': 'published', 'published': True}}
    _store(tmp_path, [('2026-10-08', rows, dec)])
    res = fb.build_v2(fb.classify(fb.collect_days(tmp_path / 'dec', tmp_path / 'inbox'), now=NOW))
    priors, stats = fb.write_v2(res, store=tmp_path / 'fb', now=NOW)
    a1 = priors['accounts']['a1']['overall']
    assert (a1['published_edited'], a1['approved'], a1['unpicked']) == (1, 1, 1)
    assert priors['accounts']['a2']['overall']['unpicked'] == 1
    raw = (tmp_path / 'fb' / 'stats.json').read_text()
    assert 'SECRET' not in raw and 'draft e' not in raw and stats['edit_examples'] == 2
    ex = [json.loads(x) for x in (tmp_path / 'fb' / 'style_examples' / 'a1.jsonl').read_text().splitlines()]
    assert {e['outcome'] for e in ex} == {'published_edited', 'approved'} and '+SECRET edited body' in ex[0]['diff']


def test_open_day_has_no_unpicked(tmp_path):
    rows = [row('p'), row('q')]
    _store(tmp_path, [('2026-10-09', rows, {'p': {'id': 'p', 'action': 'published', 'published': True}})])
    got = {r['id']: oc for _, r, _, oc in fb.classify(fb.collect_days(tmp_path / 'dec', tmp_path / 'inbox'), now=NOW)}
    assert got == {'p': 'published_asis', 'q': 'none'}


def test_v1_priors_still_load_without_account_minimum():
    v1 = {'a1': {'overall': {'approve_rate': 0.5, 'n': 3}, 'angle': {'x': {'approve_rate': 0.8, 'n': 3}}}}
    assert fb.angle_multiplier(v1, 'a1', 'x') == 1.15


# ------------------------------------------------------------------ nightly script + /admin panel

def _run(tmp_path, **env):
    e = {**os.environ, 'FD_COMPOSE_INBOX': str(tmp_path / 'inbox'), 'FD_ADMIN_DECISIONS': str(tmp_path / 'dec'),
         'FD_FEEDBACK_STORE': str(tmp_path / 'fb'), **env}
    return subprocess.run([sys.executable, str(ROOT / 'scripts/feedback_priors.py')], env=e, capture_output=True,
                          text=True, timeout=60)


def test_nightly_script_v2_and_rollback(tmp_path):
    rows, dec = _decided(3, 3)
    _store(tmp_path, [('2026-10-07', rows, dec)])
    r = _run(tmp_path)
    assert r.returncode == 0 and 'feedback v2' in r.stdout and 'published 3' in r.stdout
    assert json.loads((tmp_path / 'fb' / 'priors.json').read_text())['version'] == 'feedback-v2'
    assert (tmp_path / 'fb' / 'stats.json').exists()
    r = _run(tmp_path, FD_FEEDBACK_V2='0')
    assert r.returncode == 0 and 'feedback v1' in r.stdout and not (tmp_path / 'fb' / 'stats.json').exists()
    assert json.loads((tmp_path / 'fb' / 'priors.json').read_text())['version'] == 'feedback-v1'
    assert 'off' in _run(tmp_path, FD_FEEDBACK='0').stdout


def test_admin_panel_embeds_stats(tmp_path, monkeypatch):
    rows, dec = _decided(3, 3)
    _store(tmp_path, [('2026-10-07', rows, dec)])
    assert _run(tmp_path).returncode == 0
    monkeypatch.setenv('FD_FEEDBACK_STORE', str(tmp_path / 'fb'))
    st = admin.feedback_stats()
    assert st['totals']['published'] == 3 and st['min_account'] == fb.MIN_ACCOUNT_N
    assert 'draft a1p0' not in json.dumps(st, ensure_ascii=False)
    assert 'id="fbp"' in admin.PAGE and 'fbPanel()' in admin.PAGE
    monkeypatch.setenv('FD_FEEDBACK_STORE', str(tmp_path / 'none'))
    assert admin.feedback_stats() is None
