import json
from live.content_store import ContentStore


def test_invalid_view_sidecar_entry_is_skipped_not_fatal(tmp_path):
    unit = {'kind': 'view', 'statement': 'Demand drives revenue.', 'source_spans': [{'exact_text': 'Revenue rose 10% as demand improved.'}]}
    row = {'unit_id': 'u1', 'unit': unit, 'licence_tier': 'B', 'source': {'source_id': 's', 'source_hash': 'h'}}
    (tmp_path / 'units.jsonl').write_text(json.dumps(row) + '\n')
    bad = {'unit_id': 'u1', 'view': {'direction': 'bullish', 'conviction': 'high', 'horizon': 'months', 'subject': 'x',
                                     'reasoning': ['Revenue rose 99%.']}}
    (tmp_path / 'view_enrich.jsonl').write_text(json.dumps(bad) + '\n')
    store = ContentStore(tmp_path)
    assert store.view_errors and store.view_errors[0]['unit_id'] == 'u1'
