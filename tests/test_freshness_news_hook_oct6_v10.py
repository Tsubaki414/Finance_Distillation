"""Oct 6 v10: in-shelf tier for timely beats + news-hook (same event) dedupe in demo selection.

Fiona on the v9 pack: "这是今天收取的素材写出来的吗？怎么选题还在非农数据上，这过去几天了？"
"""
from datetime import date, datetime, timedelta, timezone
import json

import pytest

import scripts.demo_matrix_compose as demo
from live import anti_repeat, freshness, news_hook


def _rec(source, kind, published, *, title='T', statement='', subject=None, adapter='newsletter', lang='en'):
    unit = {'kind': kind, 'as_of': published[:10], 'published_at': published, 'source_spans': [],
            'statement': statement}
    if subject:
        unit['view'] = {'subject': subject}
    return {'unit_id': f'{source}-{kind}', 'licence_tier': 'A',
            'source': {'source_hash': source, 'id': source, 'adapter': adapter, 'source_id': 'nl-' + source,
                       'published_at': published, 'title': title, 'source_language': lang},
            'unit': unit}


def _packet(source, published, **kw):
    return [_rec(source, 'view', published, **kw), _rec(source, 'fact', published, **kw)]


@pytest.fixture
def pools(monkeypatch):
    monkeypatch.setattr(demo, 'has_valid_view', lambda unit: unit.get('kind') == 'view')
    monkeypatch.setattr(freshness, 'today', lambda: date(2026, 10, 6))
    data = {}
    monkeypatch.setattr(demo, 'units_for_persona', lambda store, account, **_k: data.get(account, []))
    return data


# ---------- news_hook ----------

def test_hooks_detect_payroll_release_en_and_zh():
    assert 'us_payrolls' in news_hook.hooks('September 2026 Labor Market Recap')
    assert 'us_payrolls' in news_hook.hooks('Market Gains Momentum after Soft Jobs Report')
    assert 'us_payrolls' in news_hook.hooks('Adding just 29,000 jobs removes the inflationary pressure')
    assert 'us_payrolls' in news_hook.hooks('9月非农新增就业远不及预期')
    assert news_hook.hooks('France is the Biggest Loser in the Global Rates Reset') == set()
    assert 'fomc_decision' not in news_hook.hooks('此次加息后美联储其实一点都不急着继续动手')   # rate path talk is not the meeting


def test_packet_hook_needs_title_subject_or_two_mentions():
    one_mention = [_rec('a', 'view', '2026-10-05', statement='Rates reset; payrolls were soft too'),
                   _rec('a', 'fact', '2026-10-05', statement='OAT spread widened 20bp')]
    assert news_hook.packet_hooks(one_mention) == set()
    two = [_rec('a', 'view', '2026-10-05', statement='payrolls soft'), _rec('a', 'fact', '2026-10-05', statement='payrolls +29k')]
    assert news_hook.packet_hooks(two) == {'us_payrolls'}
    assert news_hook.packet_hooks(_packet('b', '2026-10-02', title='Soft Jobs Report')) == {'us_payrolls'}


def test_history_hooks_window():
    now = datetime(2026, 10, 6, tzinfo=timezone.utc)
    rows = [{'ts': (now - timedelta(days=10)).isoformat(), 'text': 'CPI hot', 'subject': 'cpi'},
            {'ts': (now - timedelta(hours=2)).isoformat(), 'text': 'Adding just 29,000 jobs', 'subject': 'fed'},
            {'text': 'no ts', 'subject': 'x', 'news_hooks': ['china_pmi']}]
    assert set(news_hook.history_hooks(rows, now)) == {'us_payrolls', 'china_pmi'}


def test_record_draft_stores_source_title_and_hooks(tmp_path, monkeypatch):
    monkeypatch.setattr(anti_repeat, 'HISTORY_DIR', tmp_path)
    monkeypatch.setattr(anti_repeat, 'FALLBACK_DIR', tmp_path)
    anti_repeat.record_draft('p1', 'Wage growth cooled.\nWhy pretend?', meta={'source_title': 'September 2026 Labor Market Recap'})
    row = anti_repeat.load_recent('p1')[-1]
    assert row['source_title'] == 'September 2026 Labor Market Recap'
    assert row['news_hooks'] == ['us_payrolls']


# ---------- in-shelf tier ----------

def test_in_shelf_beats_theme_fresh_old_packet(pools, monkeypatch):
    monkeypatch.setattr(demo, 'group_theme_repeat', lambda g, recent: g[0]['source']['id'] == 'new')
    pools['en_industry'] = _packet('old', '2026-09-17T00:00:00Z') + _packet('new', '2026-10-05T00:00:00Z')
    sel = {}
    chosen = demo.select_groups(object(), ['en_industry'], sel)
    assert chosen['en_industry'][0]['source']['id'] == 'new'
    assert sel['en_industry']['in_shelf'] is True and sel['en_industry']['freshness_fallback'] is None


def test_fallback_recorded_with_chain_exclusions(pools):
    pools['en_industry'] = _packet('old', '2026-09-17T00:00:00Z') + _packet('today', '2026-10-06T00:00:00Z')
    sel = {}
    chosen = demo.select_groups(object(), ['en_industry'], sel, exclude_sources={'today'})
    assert chosen['en_industry'][0]['source']['id'] == 'old'
    fb = sel['en_industry']['freshness_fallback']
    assert fb['reason'] == 'no_in_shelf_candidate' and fb['in_shelf_candidates'] == 0
    assert fb['in_shelf_excluded_by_chain'] == 1 and fb['chosen_published_at'].startswith('2026-09-17')


def test_in_shelf_failing_prescreen_falls_back_and_says_why(pools, monkeypatch):
    real = demo.prescreen.prescreen
    monkeypatch.setattr(demo.prescreen, 'prescreen',
                        lambda account, g: {'ok': False, 'reason': 'policy'} if g[0]['source']['id'] == 'new'
                        else real(account, g))
    pools['en_industry'] = _packet('old', '2026-09-17T00:00:00Z') + _packet('new', '2026-10-05T00:00:00Z')
    sel = {}
    chosen = demo.select_groups(object(), ['en_industry'], sel)
    assert chosen['en_industry'][0]['source']['id'] == 'old'
    assert sel['en_industry']['freshness_fallback']['reason'] == 'in_shelf_failed_prescreen'


def test_non_timely_beat_keeps_old_behaviour(pools):
    pools['investing_philosophy'] = _packet('old', '2026-09-17T00:00:00Z')
    sel = {}
    chosen = demo.select_groups(object(), ['investing_philosophy'], sel)
    assert chosen['investing_philosophy'] and sel['investing_philosophy']['freshness_fallback'] is None


def test_zh_fallback_names_pair_that_took_the_in_shelf_source(pools):
    fresh = _packet('fresh', '2026-10-05T00:00:00Z')
    pools['en_macro'] = list(fresh)
    pools['zh_macro'] = list(fresh) + _packet('stale', '2026-09-20T00:00:00Z')
    sel = {}
    chosen = demo.select_groups(object(), ['zh_macro', 'en_macro'], sel)
    assert chosen['zh_macro'][0]['source']['id'] == 'stale'
    assert sel['zh_macro']['freshness_fallback']['in_shelf_taken_by_pair'] == 'en_macro'


# ---------- news-hook dedupe ----------

PAYROLL_HISTORY = [{'text': 'The Fed will pause. Adding just 29,000 jobs removes the pressure.',
                    'subject': 'federal reserve interest rate hike probability'}]


def test_same_event_ranks_after_other_in_shelf_event(pools):
    pools['en_macro'] = (_packet('recap', '2026-10-02T00:00:00Z', title='September 2026 Labor Market Recap')
                         + _packet('france', '2026-10-03T00:00:00Z', title='France is the Biggest Loser in the Global Rates Reset'))
    sel = {}
    chosen = demo.select_groups(object(), ['en_macro'], sel, recent={'en_macro': PAYROLL_HISTORY})
    assert chosen['en_macro'][0]['source']['id'] == 'france'
    assert sel['en_macro']['news_hook_repeat'] == []


def test_repeated_event_still_beats_stale_but_is_flagged(pools):
    pools['en_macro'] = (_packet('recap', '2026-10-05T00:00:00Z', title='Soft Jobs Report')
                         + _packet('old', '2026-09-10T00:00:00Z', title='Something else'))
    sel = {}
    chosen = demo.select_groups(object(), ['en_macro'], sel, recent={'en_macro': PAYROLL_HISTORY})
    assert chosen['en_macro'][0]['source']['id'] == 'recap'
    assert sel['en_macro']['news_hook_repeat'] == ['us_payrolls']
    assert sel['en_macro']['freshness_fallback'] is None
