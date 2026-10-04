import json
from unittest.mock import patch
from live.content_store import ContentStore
from live.reportgem_daily import store_units
from tests.test_validate_e2e import row, FakeJev


def test_reportgem_targets_all_beats_and_keeps_low_confidence(tmp_path):
    records = [row(uid) for uid in ('yes', 'no', 'unknown', 'screened')]
    class Jev:
        def review(self, state, questions):
            answers = {}
            for key in questions:
                uid, persona = json.loads(key)
                if uid == 'unknown':
                    continue
                answers[key] = {'choice': 'relevant' if uid == 'yes' and persona == 'macro_zh' else 'irrelevant', 'confidence': .2}
            return {'status': 'completed', 'answers': answers}
    store = ContentStore(tmp_path)
    with patch('live.jev_front.prescreen_units', return_value={'screened': {'verdict': 'drop'}}):
        result = store_units(records[0]['source'], [r['unit'] for r in records], 'macro_rates_en', store=store, jev=Jev())
    assert result['dropped_untargeted'] == 2
    assert result['added'] == 1
    assert store.units()[0]['personas'] == ['macro_rates_en']
    assert store.units()[0]['persona_tags']['macro_zh']['confidence'] == .2
    assert store.units()[0]['tag_personas'] == []


def test_tag_cli_ledger_cap_and_only_untagged(tmp_path, capsys):
    from scripts.tag_store_personas import main
    from ml import budget
    (tmp_path / 'units.jsonl').write_text(''.join(json.dumps(row(uid)) + '\n' for uid in ('a', 'b')))
    ContentStore(tmp_path).set_persona_tags({'a': {'macro_zh': dict(verdict='irrelevant', confidence=.9)}}, .7)
    run = tmp_path / 'run'
    fake = FakeJev()
    with patch('live.jev_review_client.JevReviewClient', return_value=fake), patch.object(budget, 'STORE'), patch.object(budget, 'LEDGER'):
        assert main(['--store', str(tmp_path), '--jev-run', str(run), '--max-calls', '1', '--only-untagged']) == 0
        assert budget.LEDGER == run / 'ledger' / 'spend.json'
    assert len(fake.calls) == 1 and len(fake.calls[0][1]) == 10
    assert len(ContentStore(tmp_path).units()[1]['tag_personas']) == 10
    assert json.loads(capsys.readouterr().out)['stats']['calls'] == 1


def test_validator_default_tags_and_compare(tmp_path):
    from scripts.validate_e2e import main
    (tmp_path / 'units.jsonl').write_text(json.dumps(row('yes')) + '\n')
    before = tmp_path / 'before.json'; after = tmp_path / 'after.json'; md = tmp_path / 'after.md'
    fake = FakeJev()
    with patch('live.jev_review_client.JevReviewClient', return_value=fake):
        assert main(['--store', str(tmp_path), '--jev', '--mode', 'legacy', '--out-json', str(before)]) == 0
        assert main(['--store', str(tmp_path), '--jev', '--compare', str(before), '--out-json', str(after), '--out-md', str(md)]) == 0
    report = json.loads(after.read_text())
    assert report['untagged_count'] == 1
    comparison = report['comparison']['macro_rates_en']
    assert comparison['before']['served'] == 1 and comparison['before']['precision'] == 1
    assert comparison['after']['served'] == 0 and comparison['after']['precision'] is None
    assert 'Before served' in md.read_text() and 'After precision' in md.read_text()


def test_adapter_ingest_tags_after_prescreen(tmp_path):
    from scripts.run_content_adapters import main
    from tests.test_content_store import source, unit
    src = source(); units = [unit(src)]
    class Jev:
        calls = []
        def review(self, state, questions):
            self.calls.append(questions)
            return {'status': 'completed', 'answers': {k: {'choice': 'irrelevant', 'confidence': .9} for k in questions}}
    run = tmp_path / 'run'; run.mkdir()
    (run / 'sources.json').write_text(json.dumps({'text': [], 'data': [[src, units, 'bls_api']], 'adapters': {}}))
    store_dir = tmp_path / 'store'
    with patch('sys.argv', ['run_content_adapters.py', '--run', str(run), '--store', str(store_dir), '--jev']), \
         patch('live.jev_review_client.JevReviewClient', return_value=Jev()), \
         patch('live.jev_front.route_sources', return_value={src['id']: dict(persona='macro_rates_en', jev_fallback=False)}), \
         patch('live.jev_front.prescreen_units', return_value={units[0]['unit_id']: {'verdict': 'keep'}}):
        main()
    report = json.loads((run / 'report.json').read_text())
    assert report['stored']['dropped_untargeted'] == 1
    assert report['stored']['dropped_by_prescreen'] == 0
    assert ContentStore(store_dir).units() == []


def test_reportgem_without_jev_unchanged(tmp_path):
    r = row('offline')
    store = ContentStore(tmp_path)
    result = store_units(r['source'], [r['unit']], 'macro_rates_en', store=store)
    assert result['added'] == 1 and result['dropped_untargeted'] == 0
    assert not (tmp_path / 'persona_tags.jsonl').exists()
