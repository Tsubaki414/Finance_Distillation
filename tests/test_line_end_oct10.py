"""Oct 10 (Fiona): per-account line-end punctuation habit (live/line_end.py)."""
import json

import pytest

from live import line_end as L


@pytest.fixture(autouse=True)
def line_end_on(monkeypatch):
    monkeypatch.setenv('FD_LINE_END', '1')


def test_classify_classes():
    assert L.classify('今天很好。') == 'period_zh'
    assert L.classify('done.') == 'period_en'
    assert L.classify('really?') == 'question'
    assert L.classify('wow！') == 'excl'
    assert L.classify('wait...') == 'ellipsis'
    assert L.classify('等等…') == 'ellipsis'
    assert L.classify('moon 🚀') == 'emoji'
    assert L.classify('no punctuation here') == 'none'
    assert L.classify('他说「好。」') == 'period_zh'


def test_measure_skips_url_and_tag_lines():
    acc = L._blank()
    L._add(acc, 'First line.\nsecond line\nhttps://t.co/abc\n$BTC $ETH')
    s = L.summarize(acc)
    assert s['lines'] == 2 and s['line_end_period_rate'] == 0.5
    assert s['final_line_period_rate'] == 0.0


def test_never_strips_protected_endings():
    prof = {'line_period_keep': 0.0, 'final_period_keep': 0.0}
    text = '\n'.join(['Rates in the U.S.', 'See e.g.', 'Apples, pears, etc.', '1.', 'Is it?', 'Yes!', 'Hmm...',
                      'Watch $NVDA.', 'Docs at https://x.com/a.', '等等…'])
    assert L.apply(text, 'x', 'seed', prof=prof) == text


def test_strips_only_trailing_and_keeps_inline_periods():
    prof = {'line_period_keep': 0.0, 'final_period_keep': 0.0}
    out = L.apply('GDP grew 2.5% in Q3. Then it slowed.\n\n美股很强。资金还在进。', 'x', 's', prof=prof)
    assert out == 'GDP grew 2.5% in Q3. Then it slowed\n\n美股很强。资金还在进'


def test_keep_one_is_identity_and_deterministic():
    text = 'Line one.\nLine two.\nLine three.'
    assert L.apply(text, 'x', 's', prof={'line_period_keep': 1.0, 'final_period_keep': 1.0}) == text
    prof = {'line_period_keep': 0.5, 'final_period_keep': 0.5}
    assert L.apply(text, 'x', 'draft-1', prof=prof) == L.apply(text, 'x', 'draft-1', prof=prof)


def test_rate_follows_profile():
    lines = [f'Point number {i} holds.' for i in range(400)]
    out = L.apply('\n'.join(lines), 'x', 'seed', prof={'line_period_keep': 0.3, 'final_period_keep': 0.3})
    kept = sum(ln.endswith('.') for ln in out.split('\n'))
    assert 80 <= kept <= 160


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv('FD_LINE_END', '0')
    assert L.apply('a line.', 'x', 's', prof={'line_period_keep': 0.0}) == 'a line.'


def test_profile_from_stats_file(tmp_path, monkeypatch):
    p = tmp_path / 'le.json'
    p.write_text(json.dumps({'accounts': {'acct_a': {'lang': 'en', 'line_end_period_rate': 0.2,
                                                     'final_line_period_rate': 0.1, 'line_period_keep': 0.25,
                                                     'final_period_keep': 0.1},
                                          'acct_b': {'lang': 'zh', 'line_end_period_rate': 0.8,
                                                     'final_line_period_rate': 0.9, 'line_period_keep': 0.9,
                                                     'final_period_keep': 0.95}}}))
    monkeypatch.setenv('FD_LINE_END_STATS', str(p))
    assert L.profile('acct_a')['line_period_keep'] == 0.25
    assert L.profile('missing') is None
    assert L.apply('no profile.', 'missing', 's') == 'no profile.'
    h = L.prompt_habit('acct_b')
    assert h['line_end_period_rate'] == 0.8 and '。' in h['guidance']


def test_thread_parts_match_body():
    prof = {'line_period_keep': 0.4, 'final_period_keep': 0.2}
    parts = ['One thing.\nTwo things.', 'Three things.\nFour things.']
    body = L.apply('\n\n'.join(parts), 'x', 'd', prof=prof)
    assert '\n\n'.join(L.apply_parts(parts, 'x', 'd', prof=prof)) == body


def test_stats_file_has_no_donor_text():
    data = json.loads(L.STATS.read_text()) if L.STATS.exists() else {'accounts': {}}
    for acc in data['accounts'].values():
        assert set(acc) <= {'posts', 'lines', 'line_end_mix', 'final_line_mix', 'line_end_period_rate',
                            'final_line_period_rate', 'line_period_keep', 'final_period_keep', 'lang', 'donors',
                            'by_lang'}


def test_compose_applies_line_end_to_body_and_thread(tmp_path, monkeypatch):
    """The compose hook: body, text and thread parts all go through the same deterministic pass."""
    import inspect
    from live import compose
    src = inspect.getsource(compose.compose_source)
    assert '_le.apply(body, persona, base[\'id\'])' in src and 'apply_parts' in src
    assert "'line_end_habit'" in inspect.getsource(compose)
