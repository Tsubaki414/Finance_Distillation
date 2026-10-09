"""Oct 10: bucketed dedup_store == all-pairs duplicate_content result."""
import json
from live.content_store import duplicate_content
from scripts.dedup_store import dedup_store


def rec(uid, statement, pub='p', numbers=()):
    return {'unit_id': uid, 'licence_tier': 'A', 'source': {'publisher': pub, 'id': uid},
            'unit': {'unit_id': uid, 'statement': statement, 'numbers': [{'text': n} for n in numbers], 'licence_tier': 'A'}}


def test_bucketed_matches_all_pairs(tmp_path):
    rows = [rec('a', 'Bitcoin ETF inflows rose sharply on Monday', numbers=['5']),
            rec('b', 'bitcoin etf inflows rose sharply on monday!', numbers=['5']),          # exact dup of a
            rec('c', 'Bitcoin ETF inflows rose sharply on Monday', pub='q', numbers=['5']),  # other publisher
            rec('d', 'Bitcoin ETF inflows rose sharply on Monday', numbers=['6']),           # other numbers
            rec('e', 'Bitcoin ETF inflows rose sharply on Monday again', numbers=['5']),     # jaccard 7/8
            rec('f', 'Totally different claim about rates', numbers=['5'])]
    (tmp_path / 'units.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    got = [(d['unit_id'], d['kept_unit_id']) for d in dedup_store(tmp_path)]
    kept, ref = [], []
    for r in rows:
        f = next((k for k in kept if duplicate_content(k, r)), None)
        (ref.append((r['unit_id'], f['unit_id'])) if f else kept.append(r))
    assert got == ref == [('b', 'a'), ('e', 'a')]
