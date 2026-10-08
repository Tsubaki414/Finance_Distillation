"""/admin review console: decisions overlay on the public dashboard, decision merge, console build (offline)."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import apply_admin_decisions as apply  # noqa: E402
import build_admin_console as admin  # noqa: E402
import build_ops_dashboard as ops  # noqa: E402


def draft(i, status='draft_ready', text='原稿', parts=None):
    return {'id': i, 'status': status, 'note': 'x' if status != 'draft_ready' else '', 'text': text,
            'parts': parts, 'parts_w': None, 'chars': len(text), 'xw': ops.x_weight(text)}


def test_overlay_approve_hold_rewrite_edit():
    ds = [draft('a', 'HOLD'), draft('b'), draft('c'), draft('d', text='one'), draft('e', 'HOLD'),
          draft('f', parts=['p1', 'p2'])]
    ops.apply_decisions(ds, {
        'a': {'action': 'approve', 'text': '改后的稿'},
        'b': {'action': 'hold', 'note': '数字不对'},
        'c': {'action': 'rewrite', 'note': '换个角度'},
        'd': {'action': 'edit', 'text': 'two'},
        'e': {'action': 'clear', 'text': 'ignored'},
        'f': {'action': 'approve', 'text': 'q1\n\nq2\n\nq3'},
    })
    a, b, c, d, e, f = ds
    assert (a['status'], a['text'], a['note'], a['chars']) == ('draft_ready', '改后的稿', '', 4)
    assert (b['status'], b['note']) == ('HOLD', 'Fiona HOLD：数字不对')
    assert (c['status'], c['note']) == ('HOLD', 'Fiona 要求重写：换个角度')
    assert (d['status'], d['text']) == ('draft_ready', 'two')
    assert (e['status'], e['text']) == ('HOLD', '原稿')
    assert f['parts'] == ['q1', 'q2', 'q3'] and len(f['parts_w']) == 3


def test_merge_newer_wins_and_rejects_junk():
    into = {}
    apply.merge(into, {'x': {'id': 'x', 'action': 'hold', 'at': '2026-10-07T10:00:00Z'}})
    apply.merge(into, {'x': {'id': 'x', 'action': 'approve', 'text': '  t ', 'at': '2026-10-07T11:00:00Z'},
                       'y': {'id': 'y', 'action': 'publish'}, 'z': 'junk'})
    apply.merge(into, {'x': {'id': 'x', 'action': 'rewrite', 'at': '2026-10-07T09:00:00Z'}})
    assert list(into) == ['x'] and into['x']['action'] == 'approve' and into['x']['text'] == 't'


def test_apply_from_export_file_writes_store_and_rewrite_notes(tmp_path, monkeypatch):
    export = tmp_path / 'export.json'
    export.write_text(json.dumps({'day': '2026-10-07', 'decisions': {
        'k1': {'id': 'k1', 'action': 'rewrite', 'note': '别用术语', 'at': '2026-10-07T12:00:00Z'},
        'k2': {'id': 'k2', 'action': 'approve', 'at': '2026-10-07T12:00:00Z'}}}))
    store = tmp_path / 'store'
    monkeypatch.setattr(sys, 'argv', ['x', '--file', str(export), '--no-api', '--store', str(store)])
    assert apply.main() == 0
    saved = json.loads((store / '2026-10-07.json').read_text())
    assert set(saved['decisions']) == {'k1', 'k2'}
    assert json.loads((store / '2026-10-07.rewrite_notes.json').read_text()) == {'k1': '别用术语'}
    assert ops.load_decisions('2026-10-07', store)['k2']['action'] == 'approve'


def test_build_console(tmp_path, monkeypatch):
    day = tmp_path / 'inbox/2026-10-07'
    day.mkdir(parents=True)
    base = {'day': '2026-10-07', 'run_id': 'r1', 'account_id': 'acct', 'name': 'Acct', 'lang': 'zh',
            'suggested_post_time_london': '2026-10-07T09:00:00+01:00', 'stored_at': '2026-10-07T08:00:00+00:00',
            'source': {'url': 'https://example.com/a', 'title': 'T'}, 'models': ['m'], 'spend_usd': 0.2}
    rows = [dict(base, id='old', body='旧稿', draft_status='draft_ready', superseded=True, held=True),
            dict(base, id='new', body='新稿', draft_status='draft_ready', rewrite_of='old',
                 findings=[{'code': 'jargon_unexplained', 'level': 'hard'}, {'code': 'theme_repeat', 'level': 'soft'}],
                 triage={'action': 'reassign', 'from': {'account_id': 'b', 'name': 'B'}, 'at': '2026-10-07T10:00:00+00:00'})]
    for r in rows:
        (day / f"{r['id']}.json").write_text(json.dumps(r, ensure_ascii=False))
    monkeypatch.setattr(admin, 'RUNS', tmp_path / 'runs')
    monkeypatch.setattr(admin, 'DECISIONS', tmp_path / 'dec')
    out = tmp_path / 'out'
    admin.build(tmp_path / 'inbox', out)
    page = (out / 'admin/index.html').read_text()
    for f in ('api/decisions.js', 'package.json'):
        assert (out / f).exists()
    data = json.loads(page.split('<script id="data" type="application/json">')[1].split('</script>')[0]
                      .replace('<\\/', '</'))
    ds = {d['id']: d for d in data['days']['2026-10-07']}
    assert ds['old']['status'] == 'replaced' and ds['new']['status'] == 'ready'
    assert [f['level'] for f in ds['new']['findings']] == ['hard', 'warn']
    assert any('改派' in h['text'] for h in ds['new']['history'])
    assert data['runs']['2026-10-07'][0]['spend'] == 0.4 and data['target'] == 2
    assert not (out / 'middleware.js').exists() and 'authorization' not in (out / 'api/decisions.js').read_text()


def test_shared_nav_marks_current_page():
    assert ops.nav_html('/') == ('<nav class="topnav" aria-label="页面"><a href="/" aria-current=page>运营看板</a>'
                                 '<a href="/admin">审稿后台</a></nav>')
    assert '<a href="/admin" aria-current=page>审稿后台</a>' in ops.nav_html('/admin')
    for page in (ops.PAGE, admin.PAGE):
        assert '<meta name="robots" content="noindex">' in page and '__NAV__' in page and '__NAVCSS__' in page


def test_overlay_keeps_base_and_published_flag():
    ds = [draft('a'), draft('b', 'HOLD'), draft('c'), draft('d')]
    ops.apply_decisions(ds, {
        'a': {'action': 'published'},                                   # blob from before the flag existed
        'b': {'action': 'edit', 'text': '改', 'published': True},       # admin edit + 已发 coexist
        'c': {'action': 'approve', 'published': False},
    })
    a, b, c, d = ds
    assert a['published'] and a['status'] == 'draft_ready' and a['base']['status'] == 'draft_ready'
    assert b['published'] and b['text'] == '改' and b['edited'] and b['base']['text'] == '原稿' and b['status'] == 'HOLD'
    assert not c['published'] and c['decision'] == 'approve'
    assert not d['published'] and 'base' not in d
    assert ops.is_published({'action': 'published', 'published': False}) is False


def _node(script):
    node = shutil.which('node')
    if not node:
        pytest.skip('node not installed')
    r = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_next_decision_published_flag_rules():
    """api/decisions.js nextDecision (the <shared> block, also inlined into both pages)."""
    out = _node(ops.shared_js().replace('<\\/', '</') + r'''
const at = '2026-10-08T01:00:00Z', B = {day: '2026-10-08', id: 'x', account_id: 'acct'};
const go = (prev, b) => nextDecision(prev, {...B, ...b}, at);
const r = {};
// ops 已发 on an admin edit keeps the edit; unticking restores it
r.edit = go(null, {action: 'edit', text: '改后', note: ''});
r.pub = go(r.edit, {action: 'published'});
r.unpub = go(r.pub, {action: 'unpublish'});
// only 已发: ops unticks with clear
r.pure = go(null, {action: 'published'});
r.pureClear = go(r.pure, {action: 'clear'});
r.pureUnpub = go(r.pure, {action: 'unpublish'});
// admin acts after 已发: the flag stays, unpublish restores the newest admin action
r.approve = go(r.pub, {action: 'approve', text: '改后', note: ''});
r.approveUnpub = go(r.approve, {action: 'unpublish'});
// a replayed local decision (pending) carries published explicitly
r.replay = go(r.approve, {action: 'approve', text: '改后', note: '', published: false});
// blob written before the flag: action published, the previous action only in history
r.legacy = {day: B.day, id: 'x', action: 'published', text: 'T', note: '', at,
            history: [{action: 'approve', text: 'T'}, {action: 'published', text: 'T'}]};
r.legacyIs = isPublished(r.legacy);
r.legacyUnpub = go(r.legacy, {action: 'unpublish'});
r.hold = go(null, {action: 'hold', note: '数字'});
r.holdPub = go(r.hold, {action: 'published'});
r.holdPubUnpub = go(r.holdPub, {action: 'unpublish'});
console.log(JSON.stringify(r));
''')
    pick = lambda d: (d['action'], d['text'], d['published'])  # noqa: E731
    assert pick(out['pub']) == ('published', '改后', True) and out['pub']['before_publish'] == 'edit'
    assert pick(out['unpub']) == ('edit', '改后', False)
    assert pick(out['pure']) == ('published', None, True) and out['pure']['before_publish'] is None
    assert pick(out['pureClear']) == ('clear', None, False) and pick(out['pureUnpub']) == ('clear', None, False)
    assert pick(out['approve']) == ('approve', '改后', True) and pick(out['approveUnpub']) == ('approve', '改后', False)
    assert out['replay']['published'] is False
    assert out['legacyIs'] and pick(out['legacyUnpub']) == ('approve', 'T', False)
    assert (out['holdPub']['note'], out['holdPubUnpub']['action'], out['holdPubUnpub']['note']) == ('数字', 'hold', '数字')
    assert [h['action'] for h in out['unpub']['history']] == ['edit', 'published', 'unpublish']
    assert all(d['action'] in apply.ACTIONS for k, d in out.items() if isinstance(d, dict) and 'action' in d)


def test_pages_inline_shared_rule_and_live_sync(tmp_path, monkeypatch):
    day = tmp_path / 'inbox/2026-10-08'
    day.mkdir(parents=True)
    (tmp_path / 'inbox/2026-10-09').mkdir()   # an empty newer day must not become the default
    (day / 'a.json').write_text(json.dumps({'id': 'a', 'account_id': 'acct', 'body': '稿', 'draft_status': 'draft_ready',
                                            'suggested_post_time_london': '2026-10-08T09:00:00+01:00'}))
    monkeypatch.setattr(admin, 'RUNS', tmp_path / 'runs')
    monkeypatch.setattr(admin, 'DECISIONS', tmp_path / 'dec')
    monkeypatch.setattr(ops, 'DECISIONS', tmp_path / 'dec')
    out = tmp_path / 'out'
    monkeypatch.setattr(sys, 'argv', ['x', '--inbox', str(tmp_path / 'inbox'), '--out', str(out), '--no-pull'])
    assert ops.main() == 0
    for page in (out / 'index.html', out / 'admin/index.html'):
        html = page.read_text()
        assert '__SHARED__' not in html and 'function nextDecision(' in html
        assert ('id="refresh"' in html) != ('id="rf"' in html)
        assert "cache:'no-store'" in html and "/api/decisions?day=" in html and 'setInterval(' in html
        for i, js in enumerate(re.findall(r'<script>(.*?)</script>', html, re.S)):
            f = tmp_path / f'{page.parent.name}_{i}.js'
            f.write_text(js)
            if shutil.which('node'):
                assert subprocess.run(['node', '--check', str(f)], capture_output=True).returncode == 0
    ops_html = (out / 'index.html').read_text()
    assert "localStorage.getItem(LS+" not in ops_html and "action='published'" not in ops_html
    assert "on?'published'" in ops_html and "'clear':'unpublish'" in ops_html
