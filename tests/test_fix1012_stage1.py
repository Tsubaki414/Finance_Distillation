"""fix1012 stage 1 (Oct 12 2026) tests: freshness hard gate, archive humanize/line-end, one draft per account
per story per day, and the A11 opener-tic / ZH AI-template rewrite.

Each behaviour is covered by a focused test and each has a kill switch that restores the pre-fix behaviour:
  FD_FRESH_HOLD=0, FD_ONE_PER_STORY=0, FD_NAT_OPENER=0, FD_LINE_END=0, FD_HUMANIZE=0.
"""
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from live import fresh_hold, nat_tex, one_per_story  # noqa: E402


def _row(**kw):
    base = {
        'id': 'compose-abc123', 'day': '2026-10-12', 'account_id': 'crypto_btc_cycle_zh',
        'lang': 'zh', 'draft_status': 'draft_ready', 'held': False, 'hold_reason': None,
        'suggested_post_time_london': '2026-10-12T10:00:00+01:00',
        'source': {'id': 'src-1', 'url': 'https://example.com/a', 'title': 't',
                   'published_at': '2026-10-12T04:00:00+00:00'},
        'text': 'body text', 'body': 'body text',
    }
    base.update(kw)
    return base


# ------------------------------------------------------------------ fix 1: freshness hard gate

def test_fresh_hold_holds_stale_news(monkeypatch):
    """A news / original draft whose source is > 48 h old at its slot is held."""
    r = _row(source={'id': 's', 'url': 'u', 'title': 't', 'published_at': '2026-10-09T00:00:00+00:00'})
    fresh_hold.apply(r, env={})
    assert r['held'] is True
    assert r['hold_reason'].startswith('stale_source')
    assert r['draft_status'] == 'needs_review'
    assert r['fresh_hold']['age_h'] == 81.0   # 10-09 00:00Z -> 10-12 09:00Z


def test_fresh_hold_passes_fresh_news(monkeypatch):
    r = _row(source={'id': 's', 'url': 'u', 'title': 't', 'published_at': '2026-10-11T20:00:00+00:00'})
    fresh_hold.apply(r, env={})
    assert r['held'] is False
    assert r['fresh_hold']['age_h'] == 13.0   # 10-11 20:00Z -> 10-12 09:00Z


def test_fresh_hold_unknown_date_is_not_fresh():
    """Unknown publish time = not fresh for news (the 10-12 audit's `undated_kept` hole)."""
    r = _row(source={'id': 's', 'url': 'u', 'title': 't', 'published_at': None})
    fresh_hold.apply(r, env={})
    assert r['held'] is True
    assert 'unknown source publish time' in r['hold_reason']


def test_fresh_hold_archive_exempt_from_age(monkeypatch):
    """An archive row with a window (2025) date inside the freshness window does not get held on age."""
    r = _row(id='evg-200950-x-123', post_type='archive_evergreen',
             source={'id': 'x-123', 'url': 'https://x.com/a/status/1', 'title': 't',
                     'published_at': '2025-10-04T00:00:00+00:00'},
             body='常青：仓位管理的第一道防线是账户物理隔离', text='常青：仓位管理的第一道防线是账户物理隔离')
    fresh_hold.apply(r, env={})
    assert r['held'] is False
    assert r['fresh_hold'].get('archive') is True


def test_fresh_hold_archive_unframed_is_held():
    """An archive row that names an old dated event without a look-back frame is held."""
    r = _row(id='arc-200950-x-1', post_type='archive_lookback',
             body='2025年2月，SHELL 上线后价格一路走低。', text='2025年2月，SHELL 上线后价格一路走低。',
             source={'id': 'x-1', 'url': 'https://x.com/a/status/1', 'title': 't',
                     'published_at': '2025-02-27T00:00:00+00:00'})
    fresh_hold.apply(r, env={'FD_STALE_MAX_DAYS': '30'})
    assert r['held'] is True
    assert r['hold_reason'].startswith('archive_unframed')


def test_fresh_hold_kill_switch(monkeypatch):
    r = _row(source={'id': 's', 'url': 'u', 'title': 't', 'published_at': '2026-09-01T00:00:00+00:00'})
    fresh_hold.apply(r, env={'FD_FRESH_HOLD': '0'})
    assert r['held'] is False


def test_fresh_hold_never_reframes_an_existing_content_hold():
    """A row already held for a real reason keeps that reason."""
    r = _row(held=True, hold_reason='hard: fact_error',
             source={'id': 's', 'url': 'u', 'title': 't', 'published_at': '2026-09-01T00:00:00+00:00'})
    fresh_hold.apply(r, env={})
    assert r['hold_reason'] == 'hard: fact_error'


# ------------------------------------------------------------------ fix 2: archive humanize + line-end

def test_archive_humanize_row_applies_line_end(monkeypatch, tmp_path):
    """humanize_row (archive fill path) runs the per-donor line-end step, not just humanize.apply."""
    from live import archive_lookback
    calls = {}

    class FakeLE:
        @staticmethod
        def enabled():
            return True

        @staticmethod
        def apply(text, persona_or_id, seed, *, lang=None, final=True, prof=None):
            calls['le'] = (text, persona_or_id, seed, lang)
            return text.replace('。\n', '\n')

    class FakeHumanize:
        @staticmethod
        def enabled():
            return True    # isolate: only the line-end step under test

        @staticmethod
        def apply(row, client=None, lang=None, **kw):
            row['humanize'] = {'changes': []}
            return row

    monkeypatch.setitem(sys.modules, 'live.line_end', FakeLE)
    monkeypatch.setitem(sys.modules, 'live.humanize', FakeHumanize)
    row = {'id': 'evg-1-acc-1', 'account_id': 'crypto_btc_cycle_zh', 'lang': 'zh',
           'body': '第一行。\n第二行。', 'text': '第一行。\n第二行。'}
    out = archive_lookback.humanize_row(row, {'id': 'crypto_btc_cycle_zh', 'lang': 'zh'})
    assert 'le' in calls, 'line_end.apply was not called on the archive path'
    assert out['body'] == '第一行\n第二行。'
    assert out['line_end']['before'] == '第一行。\n第二行。'


def test_archive_humanize_row_never_fatal(monkeypatch):
    from live import archive_lookback

    class Boom:
        @staticmethod
        def enabled():
            raise RuntimeError('boom')

    monkeypatch.setitem(sys.modules, 'live.line_end', Boom)
    row = {'id': 'evg-1', 'account_id': 'a', 'lang': 'zh', 'body': 'x', 'text': 'x'}
    out = archive_lookback.humanize_row(row, {'id': 'a', 'lang': 'zh'})
    assert out['body'] == 'x'


# ------------------------------------------------------------------ fix 3: one draft per account per story

def test_one_per_story_holds_duplicates():
    rows = [
        _row(id='d1', stored_at='2026-10-12T03:00:00+00:00', held=True, draft_status='needs_review',
             source={'id': 's1', 'url': 'https://www.chaincatcher.com/article/2295330', 'title': 't'}),
        _row(id='d2', stored_at='2026-10-12T05:00:00+00:00', held=True, draft_status='needs_review',
             source={'id': 's2', 'url': 'https://www.chaincatcher.com/article/2295330?x=1', 'title': 't'}),
        _row(id='d3', stored_at='2026-10-12T06:00:00+00:00', held=False, draft_status='draft_ready',
             source={'id': 's3', 'url': 'https://www.chaincatcher.com/article/2295330', 'title': 't'}),
    ]
    held = one_per_story.apply(rows, env={})
    kept = [r['id'] for r in rows if not r['held']]
    assert kept == ['d3'], 'the ready row wins'
    assert {h['id'] for h in held} == {'d1', 'd2'}
    assert all(r['hold_reason'].startswith('dup_story') for r in rows if r['held'])


def test_one_per_story_different_accounts_not_affected():
    rows = [_row(id='d1', account_id='a', source={'id': 's', 'url': 'https://x.com/1', 'title': 't'}),
            _row(id='d2', account_id='b', source={'id': 's', 'url': 'https://x.com/1', 'title': 't'})]
    held = one_per_story.apply(rows, env={})
    assert held == [] and not any(r['held'] for r in rows)


def test_one_per_story_kill_switch():
    rows = [_row(id='d1', source={'id': 's', 'url': 'https://x.com/1', 'title': 't'}),
            _row(id='d2', source={'id': 's', 'url': 'https://x.com/1', 'title': 't'})]
    held = one_per_story.apply(rows, env={'FD_ONE_PER_STORY': '0'})
    assert held == [] and not any(r['held'] for r in rows)


def test_one_per_story_key_falls_back_to_title():
    assert one_per_story.story_key({'source': {'title': 'Same  Title'}}) == 't:sametitle'
    assert one_per_story.story_key({'source': {'url': 'https://x.com/a/?utm=1'}}) == 'u:https://x.com/a'
    assert one_per_story.story_key({'source': {}}) is None


def test_one_per_story_keeps_a_real_content_hold_reason():
    rows = [
        _row(id='d1', held=True, hold_reason='hard: fact_error',
             source={'id': 's', 'url': 'https://x.com/1', 'title': 't'}),
        _row(id='d2', held=False, draft_status='draft_ready',
             source={'id': 's', 'url': 'https://x.com/1', 'title': 't'}),
    ]
    one_per_story.apply(rows, env={})
    assert next(r for r in rows if r['id'] == 'd1')['hold_reason'] == 'hard: fact_error'


# ------------------------------------------------------------------ fix 4: opener tics / AI templates

def test_opener_ban_ngl_en():
    out, chg = nat_tex.apply_opener('ngl heading into inflation data', 'en', 'x')
    assert out == 'Heading into inflation data'
    assert any('ngl' in c for c in chg)


def test_opener_ban_idk_en():
    out, _ = nat_tex.apply_opener('idk how anyone doubts this', 'en', 'x')
    assert out == 'How anyone doubts this'


def test_opener_keeps_normal_first_line():
    out, chg = nat_tex.apply_opener('Bitcoin is at $124,000 today.', 'en', 'x')
    assert out == 'Bitcoin is at $124,000 today.' and chg == []


def test_opener_ban_applies_to_first_line_only():
    body = 'Bitcoin is fine.\nngl that number is wild'
    out, _ = nat_tex.apply_opener(body, 'en', 'x')
    assert out == body


def test_ai_template_zh_wangwang():
    out, chg = nat_tex.apply_opener('往往在流动性匮乏时补仓最容易被套', 'zh', 'x')
    assert out.startswith('在流动性匮乏时')
    assert chg


def test_ai_template_zh_not_x_but_y_is_reordered():
    out, _ = nat_tex.apply_opener('不是牛市，而是熊市反弹', 'zh', 'x')
    assert out == '熊市反弹，不是牛市'


def test_ai_template_zh_real_and_padding():
    out, _ = nat_tex.apply_opener('值得注意的是，真正的机会在现金流', 'zh', 'x')
    assert '值得注意的是' not in out
    assert '真正的' not in out


def test_opener_kill_switch():
    out, chg = nat_tex.apply_opener('ngl this is stale', 'en', 'x', env=None) if False else (None, None)
    # explicit env-driven path
    import os
    os.environ['FD_NAT_OPENER'] = '0'
    try:
        out, chg = nat_tex.apply_opener('ngl this is stale', 'en', 'x')
        assert out == 'ngl this is stale' and chg == []
    finally:
        os.environ.pop('FD_NAT_OPENER', None)


# ------------------------------------------------------------------ plumbing: real compose path wiring

def test_daily_compose_calls_both_gates_before_inbox():
    src = (ROOT / 'scripts' / 'daily_compose.py').read_text()
    add_ix = src.index('compose_inbox.add(row)')
    assert 'fresh_hold.apply(row' in src[:add_ix], 'fresh_hold must run before the inbox write'
    assert 'one_per_story.story_key(row)' in src[:add_ix], 'one_per_story must run before the inbox write'


def test_archive_path_calls_both_gates():
    src = (ROOT / 'live' / 'archive_lookback.py').read_text()
    ix = src.index('compose_inbox.add(row, base=inbox_base)')
    assert 'fresh_hold.apply(row' in src[:ix]
    assert 'one_per_story.story_key(row)' in src[:ix]


def test_final_sweep_present():
    src = (ROOT / 'scripts' / 'daily_compose.py').read_text()
    assert "summary['final_gates']" in src
