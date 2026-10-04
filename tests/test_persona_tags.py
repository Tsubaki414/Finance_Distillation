import json
import pytest
from live.content_store import ContentStore
from tests.test_validate_e2e import row, FakeJev


def test_tag_questions_grouped_and_bounded():
    from live.persona_tags import tag_units, tagged_personas
    fake = FakeJev()
    records = [row(str(i), 'x' * 500) for i in range(3)]
    for r in records:
        r['source']['title'] = 'Company outlook'
        r['unit']['kind'] = 'view'
    stats = {}
    tags = tag_units(records, jev=fake, stats=stats)
    assert [len(q) for _, q in fake.calls] == [10, 10, 10]
    assert len(tags['0']) == 10
    instructions = next(iter(fake.calls[0][1].values()))['instructions']
    assert 'Company outlook' in instructions and 'Original Bank' in instructions
    assert 'x' * 400 in instructions and 'x' * 401 not in instructions
    assert len(tagged_personas(tags['0'])) == 10
    assert stats == dict(calls=3, retries=0, splits=0, unresolved=0)


def test_retry_bisect_budget_and_no_keyword_fallback():
    from live.persona_tags import tag_units, tagged_personas
    stats = {}
    fake = FakeJev(fail=lambda q, n: len(q) > 1 or any('bad' in k for k in q))
    tags = tag_units([row('good'), row('bad')], jev=fake,
                     personas=['macro_rates_en'], stats=stats)
    assert tags['good']['macro_rates_en']['verdict'] == 'relevant'
    assert not tags.get('bad')
    assert stats == dict(calls=5, retries=2, splits=1, unresolved=1)
    stats = {}
    assert tag_units([row('bad')], jev=fake, max_calls=1, stats=stats) == {}
    assert stats['calls'] == 1 and stats['unresolved'] == 10
    assert tagged_personas({'b': dict(verdict='relevant', confidence=.69),
                            'a': dict(verdict='relevant', confidence=.7),
                            'c': dict(verdict='irrelevant', confidence=1)}) == ['a']


def test_sidecars_latest_and_tags_retrieval(tmp_path):
    from live.retrieval import units_for_persona, counts
    (tmp_path / 'units.jsonl').write_text(''.join(json.dumps(row(uid)) + '\n' for uid in ['low', 'high', 'unseen']))
    original = (tmp_path / 'units.jsonl').read_bytes()
    store = ContentStore(tmp_path)
    assert units_for_persona(store, 'macro_rates_en') == []
    store.set_persona_tags({uid: {'macro_rates_en': {'verdict': 'relevant', 'confidence': c}}
                            for uid, c in [('low', .7), ('high', .9)]}, .7)
    store.set_persona_tags({'low': {'macro_rates_en': {'verdict': 'relevant', 'confidence': .8}}}, .7)
    store = ContentStore(tmp_path)
    assert [r['unit_id'] for r in units_for_persona(store, 'macro_rates_en')] == ['high', 'low']
    assert all(r['match'] == 'tagged' for r in units_for_persona(store, 'macro_rates_en'))
    assert [r['unit_id'] for r in store.untagged()] == ['unseen']
    assert counts(store)['untagged'] == 1
    assert (tmp_path / 'units.jsonl').read_bytes() == original
    with pytest.raises(ValueError):
        units_for_persona(store, 'macro_rates_en', mode='unknown')


def test_raw_units_partial_answers_confidence_and_zero_cap():
    from live.persona_tags import tag_units
    class Partial:
        calls = 0
        def review(self, state, questions):
            self.calls += 1
            return {'status': 'completed', 'answers': {
                key: dict(choice='relevant', confidence=.8 if json.loads(key)[1] == 'macro_zh' else None)
                for key in questions}}
    u = dict(row('raw')['unit'], publisher='Bank', title='Raw title')
    jev = Partial(); stats = {}
    tags = tag_units([u], jev=jev, personas=['macro_zh', 'macro_rates_en'], stats=stats)
    assert tags == {'raw': {'macro_zh': dict(verdict='relevant', confidence=.8)}}
    assert (stats['calls'], stats['retries'], stats['unresolved']) == (2, 1, 1)
    assert tag_units([u], jev=jev, max_calls=0, stats=stats) == {}
    assert stats['calls'] == 0 and stats['unresolved'] == 10
    for kwargs in ({'max_calls': -1}, {'max_calls': True}, {'threshold': 2}, {'personas': ['unknown']}):
        with pytest.raises(ValueError):
            tag_units([u], jev=jev, **kwargs)


def test_tags_date_order_age_limit_and_latest_threshold(tmp_path):
    from live.retrieval import units_for_persona
    rows = [row('a', date='2026-10-01'), row('b', date='2026-10-02'),
            row('c', date='2026-10-02'), row('future', date='2026-10-04'), row('unknown', date=None)]
    (tmp_path / 'units.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    store = ContentStore(tmp_path)
    store.set_persona_tags({r['unit_id']: {'macro_rates_en': dict(verdict='relevant', confidence=.8)} for r in rows}, .7)
    assert [r['unit_id'] for r in units_for_persona(store, 'macro_rates_en')] == ['future', 'b', 'c', 'a', 'unknown']
    assert [r['unit_id'] for r in units_for_persona(store, 'macro_rates_en', as_of='2026-10-03', max_age_days=1, limit=1)] == ['b']
    store.set_persona_tags({'b': {'macro_rates_en': dict(verdict='relevant', confidence=.8)}}, .9)
    assert 'b' not in [r['unit_id'] for r in units_for_persona(ContentStore(tmp_path), 'macro_rates_en')]


def test_tag_instructions_are_language_neutral():
    """Chinese-language personas write in Chinese; English source units still fit their topic."""
    from live import persona_tags

    class Fake:
        def __init__(self):
            self.calls = []

        def review(self, state, questions):
            self.calls.append((state, questions))
            return {'status': 'completed', 'answers': {}}

    fake = Fake()
    persona_tags.tag_units([{'unit_id': 'u1', 'statement': 'BTC ETF inflows', 'kind': 'fact'}],
                           jev=fake, personas=['crypto_macro_zh'], max_calls=1)
    text = next(iter(fake.calls[0][1].values()))['instructions']
    assert 'language' in text.lower() and 'topic' in text.lower()
    assert 'any language' in text.lower()
