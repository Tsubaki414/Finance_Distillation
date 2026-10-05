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
    again = demo.run(tmp_path, 2, command='demo --dry')
    assert all(r['stance']['continues_view_id'] for r in again)
    assert all(r['ledger_prior_count'] == 1 for r in again)


def test_budget_probe_failure_fills_slots(tmp_path, monkeypatch):
    isolate_globals(monkeypatch)
    from live import erisedai_distillation_client

    monkeypatch.setattr(demo.compose_ab, 'probe', _ok_probe)
    monkeypatch.setattr(erisedai_distillation_client, 'relay_config', lambda: {})
    monkeypatch.setattr(erisedai_distillation_client, 'ErisedaiClient', lambda *a, **k: object())
    monkeypatch.setattr(demo, 'ContentStore', lambda path: object())
    monkeypatch.setattr(demo, 'select_groups', lambda store, accounts: {
        a: [{'unit_id': a, 'source': {'source_hash': 'h', 'id': 's'}, 'licence_tier': 'A', 'unit': {}}]
        for a in accounts})
    monkeypatch.setattr(demo, 'evidence_source', lambda records: (
        {'id': records[0]['unit_id'], 'source_hash': 'hash'}, []))

    def boom(*_a, **_k):
        raise budget.BudgetExceeded('refused before request')

    monkeypatch.setattr(demo.compose, 'compose_source', boom)
    results = demo.run(tmp_path, .01, live=True)
    assert len(results) == 4
    assert all(r['synthetic'] for r in results)
    assert 'BudgetExceeded' in (tmp_path / 'SUMMARY.md').read_text()


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
    monkeypatch.setattr(demo, 'select_groups', lambda store, accounts: {a: [{'unit_id': a}] for a in accounts})
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
    results = demo.run(tmp_path, 2, live=True)
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
