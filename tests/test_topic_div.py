"""Oct 8 topic diversity (FD_TOPIC_DIV) + Sirius-list X breadth sources (live/x_breadth.py)."""
import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from live import topic_div as td, x_breadth as xb

ROOT = Path(__file__).resolve().parents[1]
REF = datetime(2026, 10, 7, 23, 53, tzinfo=timezone.utc)


def _script(name):
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ themes + donor profile

def test_themes_split_crypto_into_lanes_and_keep_market_topics():
    assert td.theme_of('Polygon taps TRON’s $94 billion stablecoin supply for cross-border transfers') == 'c_stablecoin'
    assert td.theme_of('Bitcoin briefly slides below $84,000 as crypto long liquidations reach $487 million') == 'c_perp'
    assert td.theme_of('Wells Fargo in talks with Kraken parent Payward for crypto trading liquidity') == 'c_institutional'
    assert td.theme_of('10年期美债拍卖认购倍数2.77倍创2016年来新高') == 'rates_fed'
    assert td.theme_of('今天天气不错') == 'other'


def test_donor_profile_counts_last_week_originals_only(tmp_path):
    posts = tmp_path / 'posts'
    posts.mkdir()
    rows = [
        {'created': (REF - timedelta(days=1)).strftime('%a %b %d %H:%M:%S %z %Y'), 'text': 'Stablecoin supply on TRON hits $94B'},
        {'created': (REF - timedelta(days=2)).strftime('%a %b %d %H:%M:%S %z %Y'), 'text': 'Fed yields and treasury auction demand'},
        {'created': (REF - timedelta(days=2)).strftime('%a %b %d %H:%M:%S %z %Y'), 'text': 'RT stablecoin', 'rt': True},
        {'created': (REF - timedelta(days=9)).strftime('%a %b %d %H:%M:%S %z %Y'), 'text': 'old meme coin post'},
    ]
    (posts / 'donor1.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    roster = {'persona_clusters': {'acct_a': {'donors': [{'handle': 'Donor1'}]}}}
    p = td.donor_profile('a', REF, roster, posts_dir=posts)
    assert p['posts'] == 2 and p['distinct_themes'] == 2
    assert set(p['mix']) == {'c_stablecoin', 'rates_fed'}
    assert 'trx' in p['entities_72h'] and 'text' not in json.dumps(p)


def test_source_tiers_own_first_shared_news_last():
    assert td.source_tier(True, 9, ([], 0.0)) == 0
    assert td.source_tier(False, 6, (['tron'], 0.5)) == 3
    assert td.source_tier(False, 1, (['tron'], 0.0)) == 1
    assert td.source_tier(False, 1, ([], 0.2)) == 1
    assert td.source_tier(False, 1, ([], 0.01)) == 2


# ------------------------------------------------------------------ selection

def _group(i, title, handle=None, hours_ago=3):
    t = (REF - timedelta(hours=hours_ago)).isoformat()
    src = {'id': f's{i}', 'source_hash': f'h{i}', 'title': title, 'published_at': t, 'publisher': f'@{handle}' if handle else f'pub{i}',
           'adapter': f'x:{handle}' if handle else 'rss', 'url': ''}
    return [{'unit_id': f'u{i}', 'licence_tier': 'B', 'tag_personas': [], 'source': src,
             'unit': {'kind': 'view', 'statement': title, 'numbers': []}}]


def _select(monkeypatch, pools, accounts, div=True, per_lang=None):
    dc = _script('daily_compose')
    if per_lang is not None:
        monkeypatch.setattr(dc, 'MAX_ACCOUNTS_PER_EVENT', per_lang)
    monkeypatch.setenv('FD_TOPIC_DIV', '1' if div else '0')
    monkeypatch.setenv('FD_HOTSPOT', '0')
    monkeypatch.setenv('FD_SLOT_RULE', '0')   # 2 standalone picks / account (pre-Oct 9); slot rule: test_slot_rule_oct9
    monkeypatch.setenv('FD_HEAT', '0')
    monkeypatch.setenv('FD_X_BREADTH', '0')
    monkeypatch.setattr(dc, 'ContentStore', lambda: None)
    monkeypatch.setattr(dc, 'candidates', lambda store, aid, *a, **k: list(pools[aid]))
    monkeypatch.setattr(dc.prescreen, 'prescreen', lambda a, g: {'ok': True})
    monkeypatch.setattr(dc, 'group_hooks', lambda g: set())
    monkeypatch.setattr(dc.demo, 'in_shelf', lambda g, now=None: True)
    monkeypatch.setattr(dc.registry, 'persona_for_account', lambda a: a)
    monkeypatch.setattr(dc.ph, 'load_card', lambda p: {'post_type_mix': {'quick_take': 1.0}})
    monkeypatch.setattr(dc.ph, 'choose_format', lambda *a, **k: {'type': 'quick_take', 'length': 'short', 'thread_parts': 1,
                                                                 'length_target': 200, 'shapes': []})
    monkeypatch.setattr(dc.ph, 'sample_post_time', lambda *a, **k: REF)
    monkeypatch.setattr(dc.topic_div, 'profiles', lambda ids, ref, day, **k: {a: {'mix': {}, 'entities_72h': {}, 'posts': 0,
                                                                                    'posts_per_day': 0, 'distinct_themes': 0,
                                                                                    'stories': 0, 'themes': {}} for a in ids})
    universes = {a['id']: {'angle_lead': {'macro_liquidity': 0.5, 'price_structure': 0.3, 'narrative_sector': 0.2},
                           'x_sources': [{'handle': h} for h in a.get('x', [])]} for a in accounts}
    plan, _ = dc.select(accounts, universes, date(2026, 10, 8), 2, now=REF)
    return plan


POLY = 'Polygon taps TRON’s $94 billion stablecoin supply for seamless cross-border transfers'


def test_same_story_cap_binds_two_per_language_three_in_all(monkeypatch):
    accounts = [{'id': f'e{i}', 'lang': 'en', 'retrieval_beats': []} for i in range(3)] + \
               [{'id': f'z{i}', 'lang': 'zh', 'retrieval_beats': []} for i in range(2)]
    shared = _group(1, POLY)
    pools = {a['id']: [shared] for a in accounts}
    before = _select(monkeypatch, pools, accounts, div=False, per_lang=2)
    after = _select(monkeypatch, pools, accounts, div=True, per_lang=2)
    took = lambda plan: sorted(a for a, ps in plan.items() if ps)   # noqa: E731
    assert len(took(before)) == 4                      # the 10-08 shape: 2 en + 2 zh on one story
    assert len(took(after)) == 3                       # 2 per language still, 3 accounts in all
    assert sum(1 for a in took(after) if a.startswith('e')) == 2
    # Oct 8 evening default (FD_EVENT_PER_LANG=1): one account per language per story
    now = _select(monkeypatch, pools, accounts, div=True)
    assert sorted(a[0] for a in took(now)) == ['e', 'z']


def test_own_sources_come_first_and_two_picks_differ_in_theme(monkeypatch):
    acct = [{'id': 'a', 'lang': 'en', 'retrieval_beats': ['crypto_macro_en'], 'x': ['analyst']}]
    pool = [_group(1, POLY), _group(2, 'Robinhood adds $25 million worth of bitcoin to balance sheet'),
            _group(3, 'Stablecoin flows on Tron keep rising this week, USDT dominance', handle='analyst'),
            _group(4, 'Perp funding flips negative while open interest climbs on BTC', handle='analyst')]
    plan = _select(monkeypatch, {'a': pool}, acct)
    titles = [p['title'] for p in plan['a']]
    assert all(t.startswith(('Stablecoin flows', 'Perp funding')) for t in titles)
    assert plan['a'][0]['topic_div']['tier'] == 0
    assert len({p['topic_div']['theme'] for p in plan['a']}) == 2


def test_non_crypto_account_does_not_prioritise_crypto_posts_of_its_own_x(monkeypatch):
    acct = [{'id': 'p', 'lang': 'en', 'retrieval_beats': ['macro_rates_en'], 'x': ['vc']}]
    pool = [_group(1, 'Ten-year auction demand hits a record as foreign buyers return to treasuries'),
            _group(2, 'Loving the consolidation under $100 on $HYPE, bitcoin next', handle='vc')]
    plan = _select(monkeypatch, {'p': pool}, acct)
    assert plan['p'][0]['title'].startswith('Ten-year') and plan['p'][1]['topic_div']['tier'] == 2


def test_hotspot_write_needs_an_own_or_donor_adjacent_member():
    dc = _script('daily_compose')

    class Hot:
        def __init__(self):
            self.assign = {'a': ('m1', ('h1', 's1')), 'b': ('m1', ('h2', 's2'))}
            self.rec = {}

        def record(self, account, motif, **kw):
            self.rec[account] = kw
    hot = Hot()
    div = {'meta': {('a', ('h1', 's1')): {'tier': 3}, ('b', ('h2', 's2')): {'tier': 1}}}
    dc.diversity_gate_hotspot(hot, div)
    assert set(hot.assign) == {'b'} and hot.rec['a']['decision'] == 'HOLD'


def test_flag_off_is_inert(monkeypatch):
    monkeypatch.setenv('FD_TOPIC_DIV', '0')
    assert not td.enabled()
    from live import hotspot
    assert hotspot.reach_weight() == 0.7
    monkeypatch.setenv('FD_TOPIC_DIV', '1')
    assert hotspot.reach_weight() == 0.0


def test_daily_budget_default_is_25_usd():   # Fiona, Oct 8: $25/day for 36 accounts (was 8)
    text = (ROOT / 'scripts' / 'cron' / 'daily_compose.sh').read_text()
    assert 'FD_DAILY_COMPOSE_BUDGET_USD:-25' in text


# ------------------------------------------------------------------ breadth

def test_candidates_skip_existing_and_org_handles():
    sirius = [{'handle': 'Analyst1', 'user_id': '1'}, {'handle': 'SomeProtocol', 'user_id': '2'},
              {'handle': 'Known', 'user_id': '3'}, {'handle': 'quiet', 'user_id': '4'}]
    got = xb.candidates(sirius, {'known'}, {'analyst1': {'a': 3}})
    assert [g[0] for g in got] == ['Analyst1', 'quiet']


def test_assign_same_language_by_theme_and_mentions():
    now = REF
    ev = {'handle': 'h1', 'user_id': '1', 'org': False, 'lang': 'en', 'followers': 1000, 'originals_7d': 5,
          'newest_at': (now - timedelta(hours=3)).isoformat(), 'promo_share': 0.0, 'avg_chars': 200,
          'themes': {'c_stablecoin': 4, 'c_defi': 1}, 'originals_per_day': 2}
    org = dict(ev, handle='h2', org=True)
    out = xb.assign([ev, org], {'en1': {'c_stablecoin': 0.4, 'c_defi': 0.2}, 'zh1': {'c_stablecoin': 0.5}},
                    {'en1': 'en', 'zh1': 'zh'}, {'h1': {'en1': 4}}, now)
    assert list(out) == ['en1'] and out['en1'][0][0] == 'h1'


def test_rotation_respects_cap():
    assert xb.rotation(10, '2026-10-08', 30, pages=3) == list(range(10)) or len(xb.rotation(10, '2026-10-08', 30, 3)) == 10
    assert len(xb.rotation(10, '2026-10-08', 9, pages=3)) == 3
    assert xb.rotation(10, '2026-10-08', 0) == []
    a, b = xb.rotation(10, '2026-10-08', 9, 3), xb.rotation(10, '2026-10-09', 9, 3)
    assert a != b


def test_breadth_fetch_batches_pages_and_maps_uids(tmp_path, monkeypatch):
    monkeypatch.setenv('FD_X_BREADTH_STORE', str(tmp_path))
    subs = [{'handle': f'h{i}', 'user_id': str(i), 'accounts': ['a'], 'breadth': True} for i in range(3)]
    created = (REF - timedelta(hours=2)).strftime('%a %b %d %H:%M:%S %z %Y')
    calls = []

    def search(query, cursor=None):
        calls.append((query, cursor))
        return {'posts': [{'uid': '1', 'created': created}, {'uid': '2', 'created': created}]}
    import scrape_donor_posts  # noqa: F401 - on sys.path via _script
    monkeypatch.setattr(sys.modules['scrape_donor_posts'], 'timeline_posts', lambda page: page['posts'])
    out, info = xb.fetch(subs, now=REF, day='2026-10-08', window_hours=24, config={'daily_call_cap': 5, 'batch_size': 20,
                                                                                    'pages_per_batch': 3}, search=search)
    assert set(out) == {'h1', 'h2'} and info['calls'] == 1   # no cursor -> one page
    assert 'from:h0 OR from:h1 OR from:h2' in calls[0][0]


def test_x_daily_gathers_breadth_through_the_same_filters():
    from live import x_daily
    now = REF
    core = [{'handle': 'core1', 'source_id': 'x_core1', 'accounts': ['a'], 'roles': ['CORE'], 'tier': 'B', 'core': True,
             'beats': [['b']]}]
    wide = [{'handle': 'wide1', 'source_id': 'x_wide1', 'accounts': ['a'], 'roles': ['BREADTH'], 'tier': 'B',
             'core': False, 'breadth': True, 'beats': [['b']]}]
    post = lambda i, text: {'id': str(1000 + i), 'created': (now - timedelta(hours=2)).strftime('%a %b %d %H:%M:%S %z %Y'),  # noqa: E731
                            'text': text, 'rt': False, 'reply': False}
    long = 'Stablecoin supply on TRON keeps climbing while bridge volumes fall, a shift worth tracking closely this week.'
    got = x_daily.gather({}, now=now, subs=core + wide, rapid=lambda h, uids: [post(1, long)],
                         apify=lambda hs, since: ({}, {}),
                         breadth=lambda bsubs: ({'wide1': [post(2, 'Perp funding flipped negative on three venues while open interest kept rising, a squeeze setup.')]}, {'run_handles': ['wide1']}))
    assert {s['adapter'] for s in got['selected']} == {'x:core1', 'x:wide1'}
    assert got['breadth'] == {'run_handles': ['wide1']}
