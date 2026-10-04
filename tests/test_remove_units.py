import json
from scripts.remove_units import remove_units


def write(path, rows):
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))


def test_removes_units_and_sidecar_rows_and_logs(tmp_path):
    write(tmp_path/'units.jsonl', [{'unit_id': 'a', 'source': {'source_id': 'ch100'}}, {'unit_id': 'b', 'source': {'source_id': 'x'}}])
    write(tmp_path/'persona_tags.jsonl', [{'unit_id': 'a', 'tags': {}}, {'unit_id': 'b', 'tags': {}}])
    write(tmp_path/'suppressed.jsonl', [{'unit_id': 'b', 'duplicate_of': 'a'}])
    log = tmp_path/'removed.json'
    r = remove_units(tmp_path, {'a'}, reason='tdm_reserved', log=log)
    assert r['removed_units'] == ['a']
    assert [json.loads(l)['unit_id'] for l in (tmp_path/'units.jsonl').read_text().splitlines()] == ['b']
    assert [json.loads(l)['unit_id'] for l in (tmp_path/'persona_tags.jsonl').read_text().splitlines()] == ['b']
    assert (tmp_path/'suppressed.jsonl').read_text() == ''
    saved = json.loads(log.read_text())
    assert saved['reason'] == 'tdm_reserved' and saved['removed_units'] == ['a'] and saved['rows'][0]['unit_id'] == 'a'


def test_unknown_ids_are_noop(tmp_path):
    write(tmp_path/'units.jsonl', [{'unit_id': 'b'}])
    assert remove_units(tmp_path, {'zz'}, reason='x', log=tmp_path/'l.json')['removed_units'] == []
