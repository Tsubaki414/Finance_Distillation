"""Oct 13 thin lanes: extra analysis feeds for SUPPLY-bound accounts behind FD_THIN_LANE_SRC (no network here)."""
import json
import re
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from live import fd_accounts, registry, source_routes, thin_lane_src
from live.adapters import feeds

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / 'live' / 'source_registry.json'
LIC = ROOT / 'live' / 'source_licence.json'
BASE = '2863f75'   # fd-phase0 HEAD the thin lanes branch started from


def _old_newsletter_feeds():
    """The pre-Oct-13 body of run_content_adapters.newsletter_feeds."""
    rows = json.loads(REG.read_text())['sources']
    return [r for r in rows if r.get('type') in ('newsletter', 'wechat')
            and (r.get('feed_url') or (r.get('page_fetch') or {}).get('listing_url')) and not r.get('fetch_blocked')]


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('FD_THIN_LANE_SRC', '1')


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setenv('FD_THIN_LANE_SRC', '0')


def test_config_loads_and_rows_are_complete():
    cfg = json.loads(thin_lane_src.PATH.read_text())
    accounts = {a['id']: a for a in fd_accounts.rows(ROOT / 'live' / 'fd20_accounts.json')}
    rows = cfg['sources']
    assert rows and len({r['id'] for r in rows}) == len(rows)
    base_ids = {r['id'] for r in json.loads(REG.read_text())['sources']}
    for r in rows:
        assert r['id'] not in base_ids
        assert r['type'] == 'newsletter' and r['adapter'] == 'feed' and r['enabled'] is True
        assert r['feed_url'].startswith('https://')
        assert 'polymarket' not in json.dumps(r).lower()
        assert r['route_accounts'] and set(r['route_accounts']) <= set(accounts)
        assert r['route_beats']
        # every route beat is one of the routed accounts' own retrieval beats (units land in their pools)
        for aid in r['route_accounts']:
            assert set(r['route_beats']) & set(accounts[aid]['retrieval_beats']), (r['id'], aid)
        lic = cfg['licence'][r['id']]
        assert lic['tier'] in ('A', 'B') and lic.get('aliases')
        if r.get('topic_filter'):
            re.compile(r['topic_filter'])
    assert set(cfg['licence']) == {r['id'] for r in rows}


def test_switch_default_on(monkeypatch):
    monkeypatch.delenv('FD_THIN_LANE_SRC', raising=False)
    assert thin_lane_src.enabled() and thin_lane_src.rows()


def test_off_restores_the_old_feed_set(off):
    from scripts import run_content_adapters as rca
    assert rca.newsletter_feeds() == _old_newsletter_feeds()


def test_on_adds_only_the_thin_lane_feeds(on):
    from scripts import run_content_adapters as rca
    new = rca.newsletter_feeds()
    assert new[:len(_old_newsletter_feeds())] == _old_newsletter_feeds()
    assert {r['id'] for r in new[len(_old_newsletter_feeds()):]} == set(thin_lane_src.ids())


def test_routes_and_scope(monkeypatch):
    sid = next(iter(sorted(thin_lane_src.ids())))
    row = next(r for r in json.loads(thin_lane_src.PATH.read_text())['sources'] if r['id'] == sid)
    monkeypatch.setenv('FD_THIN_LANE_SRC', '1')
    r = source_routes.route(sid)
    assert r and set(r['accounts']) == set(row['route_accounts']) and set(r['beats']) == set(row['route_beats'])
    assert source_routes.allowed({'source_id': sid}, row['route_accounts'][0])
    assert not source_routes.allowed({'source_id': sid}, 'zh_us_stocks')
    tags = source_routes.tags_for([{'unit_id': 'u1'}], sid)
    assert set(tags['u1']) == set(row['route_beats'])
    on_routes = {k: v for k, v in source_routes._routes(str(source_routes.REGISTRY), True).items()
                 if k not in thin_lane_src.ids()}
    monkeypatch.setenv('FD_THIN_LANE_SRC', '0')
    assert source_routes.route(sid) is None and source_routes.tags_for([{'unit_id': 'u1'}], sid) == {}
    # stored units of a thin-lane source are offered to no account while the switch is off
    assert not any(source_routes.allowed({'source_id': sid}, a) for a in row['route_accounts'] + ['zh_us_stocks'])
    assert source_routes._routes(str(source_routes.REGISTRY), False) == on_routes
    # unrelated sources behave exactly as before
    assert source_routes.allowed({'source_id': 'fourpillars_research'}, 'crypto_research_zh')
    assert source_routes.allowed({'source_id': 'some_unrouted_feed'}, 'zh_us_stocks')


def test_licence_tier_follows_switch(monkeypatch):
    base = json.loads(LIC.read_text())['tiers']
    monkeypatch.setenv('FD_THIN_LANE_SRC', '0')
    assert registry._licence() == base
    assert all(registry.source_licence_tier(s) is None for s in thin_lane_src.ids())
    monkeypatch.setenv('FD_THIN_LANE_SRC', '1')
    assert all(registry.source_licence_tier(s) in ('A', 'B') for s in thin_lane_src.ids())
    assert {k: v for k, v in registry._licence().items() if k not in thin_lane_src.ids()} == base


def test_attribution_names_follow_switch(monkeypatch):
    from live import attribution_frame
    sid = next(iter(sorted(thin_lane_src.ids())))
    monkeypatch.setenv('FD_THIN_LANE_SRC', '1')
    assert attribution_frame.publisher_name(sid) and attribution_frame.aliases(sid)
    monkeypatch.setenv('FD_THIN_LANE_SRC', '0')
    assert attribution_frame.publisher_name(sid) is None and attribution_frame.aliases(sid) == []


def test_base_configs_untouched_since_branch_point():
    """source_registry.json / source_licence.json (incl. the zh_macro / en_macro policy sources) are byte-identical."""
    for path in (REG, LIC):
        try:
            old = subprocess.run(['git', 'show', f'{BASE}:live/{path.name}'], cwd=ROOT, capture_output=True,
                                 check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            pytest.skip('git history not available')
        assert path.read_bytes() == old


ITEMS = [
    {'title': 'Flash one', 'text': 'short flash', 'content_complete': True, 'url': 'https://ex.org/1'},
    {'title': 'Deep dive', 'text': 'analysis ' * 200, 'content_complete': True, 'url': 'https://ex.org/2'},
    {'title': 'Flash two', 'text': 'short', 'content_complete': True, 'url': 'https://ex.org/3'},
    {'title': 'Second deep', 'text': 'reasoning ' * 200, 'content_complete': True, 'url': 'https://ex.org/4'},
]


def test_full_only_skips_flashes_before_the_limit():
    feed = {'id': 'x', 'name': 'X', 'feed_url': 'https://ex.org/feed', 'full_only': True}
    with mock.patch('live.analysis_corpus.fetch_feed', return_value=(list(ITEMS), None)) as ff:
        out = feeds.fetch_newsletter(feed, limit=2)
    assert ff.call_args.kwargs['limit'] == 60
    assert [s['title'] for s in out['sources']] == ['Deep dive', 'Second deep']


def test_rows_without_the_new_keys_behave_as_before():
    feed = {'id': 'x', 'name': 'X', 'feed_url': 'https://ex.org/feed'}
    with mock.patch('live.analysis_corpus.fetch_feed', return_value=(list(ITEMS[:2]), None)) as ff:
        out = feeds.fetch_newsletter(feed, limit=2)
    assert ff.call_args.kwargs['limit'] == 2
    assert out['status'] == 'ok' and [s['title'] for s in out['sources']] == ['Deep dive'] and out['summary_only_items'] == 1
    topic = {**feed, 'topic_filter': 'flash'}
    with mock.patch('live.analysis_corpus.fetch_feed', return_value=(list(ITEMS), None)) as ff:
        out = feeds.fetch_newsletter(topic, limit=1)
    assert ff.call_args.kwargs['limit'] == 12 and out['items'] == 1


def test_fetch_limit_overrides_caller_limit():
    feed = {'id': 'x', 'name': 'X', 'feed_url': 'https://ex.org/feed', 'full_only': True, 'fetch_limit': 1}
    with mock.patch('live.analysis_corpus.fetch_feed', return_value=(list(ITEMS), None)):
        out = feeds.fetch_newsletter(feed, limit=2)
    assert [s['title'] for s in out['sources']] == ['Deep dive']


def test_daily_ingest_registers_thin_feeds_only_when_on(monkeypatch):
    from scripts import run_content_adapters as rca
    sid = next(iter(sorted(thin_lane_src.ids())))
    monkeypatch.setenv('FD_THIN_LANE_SRC', '1')
    assert sid in {f['id'] for f in rca.newsletter_feeds() if registry.source_licence_tier(f['id']) in ('A', 'B')}
    monkeypatch.setenv('FD_THIN_LANE_SRC', '0')
    assert sid not in {f['id'] for f in rca.newsletter_feeds()}
