import json

from scripts import demo_matrix_compose as demo
from ml import budget


def isolate_globals(monkeypatch):
    for name in ('STORE', 'LEDGER', 'RUNS', 'DISTILLATION_RUNS'):
        monkeypatch.setattr(budget, name, getattr(budget, name))
    for name in ('HISTORY_DIR', 'FALLBACK_DIR'):
        monkeypatch.setattr(demo.anti_repeat, name, getattr(demo.anti_repeat, name))


def _ok_probe(*_a, **_k):
    return {'available': True, 'response_model': 'probe-ok'}


def test_dry_artifacts_and_ledger_continuity(tmp_path, monkeypatch):
    isolate_globals(monkeypatch)
    results = demo.run(tmp_path, 2, command='demo --dry')
    assert len(results) == 4
    assert {r['arbitration']['status'] for r in results} == {'WRITE', 'HOLD'}
    assert all(not r['publishable'] and r['synthetic'] for r in results)
    assert budget.spent() == 0
    assert len(list((tmp_path / 'drafts').glob('*.json'))) == 4
    assert 'no prior views (day-1)' in (tmp_path / 'SUMMARY.md').read_text()
    # Oct 6 v7: synthetic/fallback slots never write views, so a second dry run has no prior view.
    assert not list((tmp_path / 'views').rglob('*.jsonl')) or all(
        not f.read_text().strip() for f in (tmp_path / 'views').rglob('*.jsonl'))
    again = demo.run(tmp_path, 2, command='demo --dry')
    assert not any(r['stance'].get('continues_view_id') for r in again)
    assert all(r['ledger_prior_count'] == 0 for r in again)


def test_budget_probe_failure_fills_slots(tmp_path, monkeypatch):
    isolate_globals(monkeypatch)
    from live import erisedai_distillation_client

    monkeypatch.setattr(demo.compose_ab, 'probe', _ok_probe)
    monkeypatch.setattr(erisedai_distillation_client, 'relay_config', lambda: {})
    monkeypatch.setattr(erisedai_distillation_client, 'ErisedaiClient', lambda *a, **k: object())
    monkeypatch.setattr(demo, 'ContentStore', lambda path: object())
    monkeypatch.setattr(demo, 'select_groups', lambda store, accounts, *_a, **_k: {
        a: [{'unit_id': a, 'source': {'source_hash': 'h', 'id': 's'}, 'licence_tier': 'A', 'unit': {}}]
        for a in accounts})
    monkeypatch.setattr(demo, 'evidence_source', lambda records: (
        {'id': records[0]['unit_id'], 'source_hash': 'hash'}, []))

    def boom(*_a, **_k):
        raise budget.BudgetExceeded('refused before request')

    monkeypatch.setattr(demo.compose, 'compose_source', boom)
    # v9: a cap that cannot fund the slots fails loud up front; nothing is attempted or faked
    results = demo.run(tmp_path, .01, live=True)
    assert len(results) == 4
    assert all(r['mode'] == 'error' and r['error_kind'] == 'unfunded' and not r['synthetic'] for r in results)
    assert 'FAIL LOUD' in (tmp_path / 'SUMMARY.md').read_text()
    # funded slots whose calls are refused become explicit error rows (not synthetic drafts)
    results = demo.run(tmp_path / 'b', 2.5, live=True)
    assert all(r['mode'] == 'error' and r['error_kind'] == 'budget' for r in results)
    assert 'BudgetExceeded' in (tmp_path / 'b' / 'SUMMARY.md').read_text()


def test_disabled_accounts_are_skipped(tmp_path, monkeypatch):
    isolate_globals(monkeypatch)
    root = tmp_path / 'config'
    (root / 'live').mkdir(parents=True)
    (root / 'live/accounts.json').write_text(json.dumps({'accounts': [
        {'id': a, 'enabled': a != 'zh_industry'} for a in demo.ACCOUNTS]}))
    monkeypatch.setattr(demo, 'ROOT', root)
    results = demo.run(tmp_path / 'out', 2)
    assert [r['account_id'] for r in results] == ['zh_macro', 'en_macro', 'en_industry']
    assert 'Skipped disabled accounts: zh_industry' in (tmp_path / 'out/SUMMARY.md').read_text()


def test_live_uses_direct_compose_and_adds_synthetic_hold(tmp_path, monkeypatch):
    isolate_globals(monkeypatch)
    from live import erisedai_distillation_client, stage_models
    monkeypatch.setattr(demo.compose_ab, 'probe', _ok_probe)
    monkeypatch.setattr(erisedai_distillation_client, 'relay_config', lambda: {})

    class Client:
        def __init__(self, directory, *, configuration):
            assert configuration['stage_models'] == stage_models.load()

    monkeypatch.setattr(erisedai_distillation_client, 'ErisedaiClient', Client)
    monkeypatch.setattr(demo, 'ContentStore', lambda path: object())
    monkeypatch.setattr(demo, 'select_groups', lambda store, accounts, *_a, **_k: {a: [{'unit_id': a}] for a in accounts})
    monkeypatch.setattr(demo, 'evidence_source', lambda records: (
        {'id': records[0]['unit_id'], 'source_hash': 'hash'}, []))
    calls = []

    def direct_compose(source, account, client, **kwargs):
        calls.append(account)
        assert 'stance_output' not in kwargs
        assert kwargs['post_type'] == 'judgment_take'
        assert kwargs['extracted_units'] == []
        assert str(kwargs['view_ledger'].path).startswith(str(tmp_path / 'views' / account))
        return dict(account_id=account, text='Judgment ' + account,
                    stance={'decision': 'adapt', 'account_view': 'Judgment ' + account,
                            'view': {'subject': account, 'direction': 'neutral'}},
                    units=[], draft_status='draft_ready', status='held')

    monkeypatch.setattr(demo.compose, 'compose_source', direct_compose)
    results = demo.run(tmp_path, 2.5, live=True)
    assert calls == list(demo.ACCOUNTS)
    assert all(r['mode'] == 'live' and not r['publishable'] for r in results)
    assert all(r['arbitration']['status'] == 'WRITE' for r in results)
    example = json.loads((tmp_path / 'synthetic_arbitration_example.json').read_text())
    assert {r['arbitration']['status'] for r in example} == {'WRITE', 'HOLD'}
    assert 'Synthetic arbitration example' in (tmp_path / 'SUMMARY.md').read_text()


def _rec(account, source, kind):
    return {'unit_id': f'{account}-{source}-{kind}', 'licence_tier': 'A',
            'source': {'source_hash': source, 'id': source}, 'unit': {'kind': kind}}


def test_shared_source_needs_view_and_fact_on_every_side(monkeypatch):
    """Oct 6: zh_industry got a 1-fact slice of the shared source (pure_data -> not_suitable)."""
    monkeypatch.setattr(demo, 'has_valid_view', lambda unit: unit.get('kind') == 'view')
    pools = {
        'zh_macro': [_rec('zh_macro', 'jpm', 'view'), _rec('zh_macro', 'jpm', 'fact')],
        'en_macro': [_rec('en_macro', 'jpm', 'view'), _rec('en_macro', 'jpm', 'fact')],
        # shared 'summit' is balanced for EN but pure fact for ZH -> must not be shared
        'zh_industry': [_rec('zh_industry', 'summit', 'fact'),
                        _rec('zh_industry', 'meta', 'view'), _rec('zh_industry', 'meta', 'fact')],
        'en_industry': [_rec('en_industry', 'summit', 'view'), _rec('en_industry', 'summit', 'fact')],
    }
    monkeypatch.setattr(demo, 'units_for_persona', lambda store, account, **_k: pools[account])
    chosen = demo.select_groups(object(), list(demo.ACCOUNTS))
    assert {r['source']['id'] for r in chosen['zh_macro']} == {'jpm'}   # balanced pair stays shared
    assert {r['source']['id'] for r in chosen['en_macro']} == {'jpm'}
    assert {r['source']['id'] for r in chosen['zh_industry']} == {'meta'}
    assert {r['source']['id'] for r in chosen['en_industry']} == {'summit'}
    assert all(demo.balanced(group) for group in chosen.values())


def test_no_balanced_packet_means_empty_not_pure_data(monkeypatch):
    monkeypatch.setattr(demo, 'has_valid_view', lambda unit: unit.get('kind') == 'view')
    pools = {'zh_industry': [_rec('zh_industry', 'x', 'fact')],
             'en_industry': [_rec('en_industry', 'x', 'fact')]}
    monkeypatch.setattr(demo, 'units_for_persona', lambda store, account, **_k: pools[account])
    chosen = demo.select_groups(object(), ['zh_industry', 'en_industry'])
    assert chosen == {'zh_industry': [], 'en_industry': []}


def _balanced_pools(monkeypatch, pools):
    monkeypatch.setattr(demo, 'has_valid_view', lambda unit: unit.get('kind') == 'view')
    monkeypatch.setattr(demo, 'units_for_persona', lambda store, account, **_k: pools.get(account, []))


def test_per_account_exclusion_keeps_source_for_other_account(tmp_path, monkeypatch):
    """v9b: wscn was used by en_macro only, yet the flat chain set hid it from zh_macro."""
    prev = tmp_path / 'prev'
    (prev / 'drafts').mkdir(parents=True)
    (prev / 'drafts' / 'en_macro.json').write_text(json.dumps(
        {'account_id': 'en_macro', 'source': {'id': 'wscn', 'title': 'wscn-t'}}))
    out = tmp_path / 'out'
    out.mkdir()
    used = demo.continue_batch(prev, out)
    saved = json.loads((out / 'excluded_sources.json').read_text())
    assert saved['version'] == 2 and saved['by_account'] == {'en_macro': ['wscn', 'wscn-t']}
    assert used.for_account('zh_macro') == set() and used.for_account('en_macro') == {'wscn', 'wscn-t'}
    _balanced_pools(monkeypatch, {
        'zh_macro': [_rec('zh_macro', 'wscn', 'view'), _rec('zh_macro', 'wscn', 'fact')],
        'en_macro': [_rec('en_macro', 'wscn', 'view'), _rec('en_macro', 'wscn', 'fact')]})
    sel = {}
    chosen = demo.select_groups(object(), ['zh_macro', 'en_macro'], sel, exclude_sources=used)
    assert chosen['en_macro'] == [] and sel['en_macro']['funnel']['excluded_used_sources'] == 1
    assert {r['source']['id'] for r in chosen['zh_macro']} == {'wscn'}
    # the v2 file round-trips for the next batch in the chain
    nxt = tmp_path / 'next'
    nxt.mkdir()
    assert demo.continue_batch(out, nxt).for_account('en_macro') >= {'wscn'}


def test_legacy_flat_excluded_sources_still_load(tmp_path, monkeypatch):
    prev = tmp_path / 'prev'
    (prev / 'drafts').mkdir(parents=True)
    (prev / 'excluded_sources.json').write_text(json.dumps(['old-a', 'old-b', 'Old title']))
    (prev / 'drafts' / 'zh_macro.json').write_text(json.dumps(
        {'account_id': 'zh_macro', 'source': {'id': 'new-z', 'title': 'new-z-t'}}))
    parent = tmp_path / 'parent'   # chain parent named on prev's SUMMARY Command line
    (parent / 'drafts').mkdir(parents=True)
    (parent / 'drafts' / 'en_macro.json').write_text(json.dumps({'account_id': 'en_macro', 'source': {'id': 'old-a'}}))
    (prev / 'SUMMARY.md').write_text(f'# x\n\nCommand: `python demo.py --live --continue-from {parent}`\n')
    (prev / 'history').mkdir()
    (prev / 'history' / 'zh_industry.jsonl').write_text(json.dumps({'text': 't', 'source_hash': 'h-b'}) + '\n')
    out = tmp_path / 'out'
    out.mkdir()
    used = demo.continue_batch(prev, out)
    assert set(used) == {'old-a', 'old-b', 'Old title', 'new-z', 'new-z-t', 'h-b'}
    assert used.by_account['en_macro'] == {'old-a'} and used.unattributed == {'old-b', 'Old title'}
    assert used.for_account('zh_macro') == {'new-z', 'new-z-t', 'old-b', 'Old title'}
    # a plain flat set passed to select_groups still applies to every account
    _balanced_pools(monkeypatch, {'en_industry': [_rec('en_industry', 'old-a', 'view'), _rec('en_industry', 'old-a', 'fact')]})
    assert demo.select_groups(object(), ['en_industry'], exclude_sources={'old-a'}) == {'en_industry': []}
    # an unattributed legacy entry whose document hash a history row names belongs to that account only
    rec = lambda a: [dict(_rec(a, 'old-b', k), source={'id': 'old-b', 'source_hash': 'h-b'}) for k in ('view', 'fact')]
    _balanced_pools(monkeypatch, {'zh_industry': rec('zh_industry'), 'en_industry': rec('en_industry')})
    chosen = demo.select_groups(object(), ['zh_industry', 'en_industry'], exclude_sources=used)
    assert chosen['zh_industry'] == [] and chosen['en_industry']


def _live_setup(monkeypatch, pools):
    from live import erisedai_distillation_client
    monkeypatch.setattr(demo.compose_ab, 'probe', _ok_probe)
    monkeypatch.setattr(erisedai_distillation_client, 'relay_config', lambda: {})
    monkeypatch.setattr(erisedai_distillation_client, 'ErisedaiClient', lambda *a, **k: object())
    monkeypatch.setattr(demo, 'ContentStore', lambda path: object())
    monkeypatch.setattr(demo, 'slot_cost_model', lambda root: dict(demo.COST_DEFAULTS, source='test'))
    monkeypatch.setattr(demo.prescreen, 'prescreen', lambda account, group: {'ok': True})
    monkeypatch.setattr(demo, 'evidence_source', lambda records: (
        {'id': records[0]['source']['id'], 'source_hash': 'hash'}, []))
    _balanced_pools(monkeypatch, pools)
    calls = []

    def compose_source(source, account, client, **kwargs):
        calls.append(account)
        return dict(account_id=account, text='Judgment ' + account, units=[], draft_status='draft_ready',
                    status='held', stance={'decision': 'adapt', 'account_view': 'Judgment ' + account,
                                           'view': {'subject': account, 'direction': 'neutral'}})

    monkeypatch.setattr(demo.compose, 'compose_source', compose_source)
    return calls


def test_budget_plan_skips_no_candidate_account(tmp_path, monkeypatch):
    """v9b: the plan funded the empty zh_macro slot and left en_industry unfunded."""
    isolate_globals(monkeypatch)
    pools = {a: [_rec(a, 'src-' + a, 'view'), _rec(a, 'src-' + a, 'fact')]
             for a in ('zh_industry', 'en_macro', 'en_industry')}
    pools['zh_macro'] = [_rec('zh_macro', 'zm-only-fact', 'fact')]
    calls = _live_setup(monkeypatch, pools)
    base = round(demo.COST_DEFAULTS['stance_usd'] + demo.COST_DEFAULTS['compose_usd']
                 + demo.COST_DEFAULTS['compose_reserve_usd'], 3)
    cap = round(3 * base + 0.01, 3)   # funds 3 slots, not 4
    results = {r['account_id']: r for r in demo.run(tmp_path, cap, live=True)}
    assert sorted(calls) == ['en_industry', 'en_macro', 'zh_industry']
    plan = json.loads((tmp_path / 'budget_plan.json').read_text())
    assert plan['slots'] == 3 and plan['slots_funded'] == 3 and plan['no_candidate_accounts'] == ['zh_macro']
    zm = results['zh_macro']
    assert zm['mode'] == 'error' and zm['error_kind'] == 'no_candidate'
    assert zm['slot_cap_usd'] == 0.0 and zm['spend_usd'] == 0
    assert zm['funnel']['tagged_sources'] == 1 and zm['funnel']['no_valid_view_sources'] == 1
    assert all(results[a]['mode'] == 'live' for a in ('zh_industry', 'en_macro', 'en_industry'))
    summary = (tmp_path / 'SUMMARY.md').read_text()
    assert 'Selection funnel' in summary and 'No candidate (zero need' in summary
    # FAIL LOUD still applies to the slots that do have a candidate
    results = demo.run(tmp_path / 'b', round(2 * base + 0.01, 3), live=True)
    kinds = {r['account_id']: r.get('error_kind') for r in results}
    assert kinds['zh_macro'] == 'no_candidate' and list(kinds.values()).count('unfunded') == 1
    assert 'FAIL LOUD' in (tmp_path / 'b' / 'SUMMARY.md').read_text()


def test_no_candidate_error_message_has_counts(monkeypatch):
    used = demo.ExcludedSources({'zh_macro': {'u1', 'u2'}})
    pools = {'zh_macro': [_rec('zh_macro', 'u1', 'view'), _rec('zh_macro', 'u1', 'fact'),
                          _rec('zh_macro', 'u2', 'fact'),
                          _rec('zh_macro', 'f1', 'fact'), _rec('zh_macro', 'v1', 'view'),
                          dict(_rec('zh_macro', 'nolic', 'view'), licence_tier='C')]}
    _balanced_pools(monkeypatch, pools)
    sel = {}
    assert demo.select_groups(object(), ['zh_macro'], sel, exclude_sources=used) == {'zh_macro': []}
    reason = demo.no_candidate_result('zh_macro', sel['zh_macro'])['error']
    assert reason.startswith('no balanced packet: 6 tagged units/5 sources within 45d')
    assert '1 sources dropped by licence' in reason
    assert '2 sources excluded as already used by this account (1 of them balanced)' in reason
    assert '2 remaining lacked a valid view + fact (1 no valid view, 1 no fact)' in reason
    assert 'No eligible tagged evidence' not in reason


def test_legacy_parent_inferred_only_from_unique_exact_sibling(tmp_path):
    """v8 crashed before SUMMARY.md; its parent (v7) is the one sibling whose used set equals its list."""
    def batch(name, excluded, drafts):
        b = tmp_path / name
        (b / 'drafts').mkdir(parents=True)
        if excluded is not None:
            (b / 'excluded_sources.json').write_text(json.dumps(excluded))
        for account, sid in drafts.items():
            (b / 'drafts' / (account + '.json')).write_text(json.dumps({'account_id': account, 'source': {'id': sid}}))
        return b
    batch('v7', ['a'], {'en_macro': 'b'})
    batch('v7zh', ['a', 'b'], {'zh_macro': 'c'})          # superset -> not a match
    v8 = batch('v8', ['a', 'b'], {'zh_macro': 'd'})
    assert demo._chain_parents(v8) == [(tmp_path / 'v7').resolve()]
    legacy = demo.load_excluded(v8)   # 'a' is v7's own inherited entry, not attributable -> all accounts
    assert legacy.by_account.get('en_macro') == {'b'} and legacy.unattributed == {'a'}
    batch('v7_copy', ['a'], {'zh_industry': 'b'})          # second exact match -> ambiguous, no parent
    assert demo._chain_parents(v8) == []
