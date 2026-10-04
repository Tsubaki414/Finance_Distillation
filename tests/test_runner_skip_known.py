import json
from scripts import run_content_adapters as r


def test_filter_known_drops_sources_already_in_store(tmp_path):
    (tmp_path / 'units.jsonl').write_text(json.dumps({'unit_id': 'u1', 'source': {'source_hash': 'h1', 'url': 'https://a/x'}}) + '\n')
    srcs = [{'id': 'a', 'source_hash': 'h1', 'url': 'https://a/y'}, {'id': 'b', 'source_hash': 'h2', 'url': 'https://a/x'},
            {'id': 'c', 'source_hash': 'h3', 'url': 'https://a/z'}]
    keep, skipped = r.filter_known(srcs, tmp_path)
    assert [s['id'] for s in keep] == ['c']
    assert sorted(skipped) == ['a', 'b']


def test_filter_known_missing_store_keeps_all(tmp_path):
    keep, skipped = r.filter_known([{'id': 'a', 'source_hash': 'h', 'url': 'u'}], tmp_path / 'none')
    assert len(keep) == 1 and skipped == []
