"""/admin review console: decisions overlay on the public dashboard, decision merge, console build (offline)."""
import json
import sys
from pathlib import Path

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
