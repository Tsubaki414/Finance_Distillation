"""Oct 8 pm-voice: market_data_charts breadth sources from its donors' @-mentions, merge-only assignment, and the
donor review of the US-stock / philosophy rosters (handles-only configs)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from live import registry, x_breadth as xb

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
REMOVED = {'zh_us_stocks': {'huahuayjy', 'silverfang88'},
           'investing_philosophy': {'DoveyWan', 'lazyvillager1', 'Shaughnessy119'},
           'single_stock_deepdive_en': {'Shaughnessy119', 'DeFiMinty'},
           'zh_longterm_investing': {'nbblock', 'yuyue_chris'},
           # Oct 9 pm-donors5: #7 / #17 lose the merged donors they shared with #1 / #11 / #14
           'crypto_btc_cycle_zh': {'thankUcrypto', 'BensonTWN', 'dapangdun', 'timotimo007'},
           'crypto_research_en': {'amandacassatt', 'sjdedic', 'econoar', '0xLuo', 'ahboyash'}}


def test_mention_candidates_need_two_citing_donors_unless_roster_extra():
    by_donor = {'chartguy': {'d1': 3, 'd2': 1}, 'onefan': {'d1': 9}, 'rosterdonor': {'d1': 1},
                'unusedmacro': {}, 'SomeCapital': {'d1': 2, 'd2': 2}, 'known': {'d1': 2, 'd2': 2}}
    got = xb.mention_candidates(by_donor, {'known'}, uids={'rosterdonor': '42'}, min_donors=2,
                                extra={'rosterdonor', 'unusedmacro'})
    names = [g[0] for g in got]
    assert names[0] == 'chartguy'                    # most citing donors first
    assert 'onefan' not in names                     # one donor only
    assert 'SomeCapital' not in names                # org-looking handle (capital$)
    assert 'known' not in names                      # already a source / donor
    assert ('rosterdonor', '42', 1, {'d1': 1}) in got and 'unusedmacro' in names


def test_merge_assigned_adds_picks_and_keeps_existing_handles():
    handles = {'Old1': {'lang': 'en', 'accounts': ['a'], 'scores': {'a': 0.5}, 'originals_per_day': 1.0}}
    evals = {'new1': {'handle': 'new1', 'lang': 'en', 'originals_per_day': 2.0}}
    out = xb.merge_assigned(handles, {'mdc': [('new1', 0.7, {})], 'other': [('new1', 0.9, {})]}, evals, ['mdc'])
    assert out['Old1'] == handles['Old1']
    assert out['new1'] == {'lang': 'en', 'accounts': ['mdc'], 'scores': {'mdc': 0.7}, 'originals_per_day': 2.0}


def test_assign_only_named_accounts_by_language():
    ev = {'handle': 'charts1', 'user_id': '1', 'org': False, 'lang': 'en', 'followers': 9000, 'originals_7d': 6,
          'newest_at': (NOW - timedelta(hours=5)).isoformat(), 'promo_share': 0.0, 'avg_chars': 150,
          'themes': {'index_breadth': 4, 'rates_fed': 2}, 'originals_per_day': 1.2}
    out = xb.assign([ev], {'market_data_charts': {'index_breadth': 0.3, 'rates_fed': 0.2}},
                    {'market_data_charts': 'en'}, {'charts1': {'market_data_charts': 3}}, NOW)
    assert [h for h, _, _ in out['market_data_charts']] == ['charts1']


def test_market_data_charts_has_breadth_handles_and_the_rest_is_unchanged():
    cfg = json.loads((ROOT / 'live' / 'x_breadth.json').read_text())
    mdc = [h for h, v in cfg['handles'].items() if 'market_data_charts' in v['accounts']]
    assert 8 <= len(mdc) <= 15
    assert all(cfg['handles'][h]['lang'] == 'en' for h in mdc)
    assert cfg['merged'][-1]['accounts'] == ['market_data_charts'] and set(cfg['merged'][-1]['added']) == set(mdc)
    # handles only: no ids, no text
    assert not any(k in json.dumps(cfg) for k in ('user_id', '"text"'))


def test_reviewed_rosters_drop_off_topic_donors_and_stay_valid():
    personas = registry.load_personas()
    roster = json.loads((ROOT / 'live' / 'donors' / 'roster.json').read_text())
    merge = json.loads((ROOT / 'live' / 'fd20_donor_merge.json').read_text())
    for aid, gone in REMOVED.items():
        cluster = roster['persona_clusters']['acct_' + aid]
        handles = {d['handle'] for d in cluster['donors']}
        assert not handles & gone, aid
        assert len(handles) >= registry.MIN_EXEMPLARS
        assert abs(sum(d['weight'] for d in cluster['donors']) - 1) < 0.001
        assert not set(merge['accounts'][aid]['donors']) & gone
        assert set(personas[aid].donor_weights) == handles
    logged = {(r['account'], r['handle']) for r in merge['removed']}
    assert logged == {(a, h) for a, hs in REMOVED.items() for h in hs}
