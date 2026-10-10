"""persona_factory.merge_cluster: a donor named in an account list without donors{} meta is skipped with a warning."""
import json
from pathlib import Path

from scripts import persona_factory as pf

ROOT = Path(__file__).resolve().parents[1]


def _roster():
    return {'donors': {}, 'persona_clusters': {'acct_x': {'donors': [
        {'handle': 'a', 'weight': 0.6}, {'handle': 'b', 'weight': 0.4}]}}}


def test_missing_donor_meta_is_skipped(capsys, monkeypatch):
    monkeypatch.setattr(pf, 'post_count', lambda h: 200)
    merge = {'version': 'v1', 'accounts': {'x': {'donors': ['ghost', 'real']}},
             'donors': {'real': {'lang': 'zh', 'category': 'crypto_macro', 'promo_share': 0.0, 'origin': 'test'}}}
    roster = _roster()
    assert pf.merge_cluster(roster, {'id': 'x', 'lang': 'zh'}, merge)
    handles = [d['handle'] for d in roster['persona_clusters']['acct_x']['donors']]
    assert handles == ['a', 'b', 'real']
    assert 'ghost' not in roster['donors']
    assert 'merged donor ghost has no donors{} meta' in capsys.readouterr().err


def test_only_missing_meta_leaves_cluster_unchanged(monkeypatch):
    monkeypatch.setattr(pf, 'post_count', lambda h: 200)
    roster = _roster()
    merge = {'version': 'v1', 'accounts': {'x': {'donors': ['ghost']}}, 'donors': {}}
    before = json.loads(json.dumps(roster))
    pf.merge_cluster(roster, {'id': 'x', 'lang': 'zh'}, merge)
    assert [d['handle'] for d in roster['persona_clusters']['acct_x']['donors']] == ['a', 'b']
    assert roster['donors'] == before['donors']


def test_live_merge_file_config_accounts_have_meta():
    """Every donor an in-config account adopts through the merge file has donors{} meta."""
    from live import fd_accounts
    merge = json.loads((ROOT / 'live' / 'fd20_donor_merge.json').read_text())
    ids = {a['id'] for a in fd_accounts.rows(pf.CONFIG)}
    dangling = [(a, h) for a, row in merge['accounts'].items() if a in ids
                for h in row.get('donors') or [] if h not in merge['donors']]
    assert dangling == []


def test_live_roster_merged_donors_are_listed():
    """A roster donor tagged 'merged' in an in-config acct_ cluster must be listed in the merge file, else
    merge_cluster strips it on the next run (pm-donors7 crypto_prediction_zh / investing_philosophy, 10-10)."""
    from live import fd_accounts
    merge = json.loads((ROOT / 'live' / 'fd20_donor_merge.json').read_text())
    roster = json.loads((ROOT / 'live' / 'donors' / 'roster.json').read_text())
    ids = {a['id'] for a in fd_accounts.rows(pf.CONFIG)}
    orphans = [(aid, d['handle']) for aid in ids
               for d in (roster['persona_clusters'].get('acct_' + aid) or {}).get('donors', [])
               if d.get('merged') and d['handle'] not in ((merge['accounts'].get(aid) or {}).get('donors') or [])]
    assert orphans == []
