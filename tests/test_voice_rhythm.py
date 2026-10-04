import json
from dataclasses import replace

import pytest

from live import compose, exemplars, registry, voice_cards
from tests.test_compose import SOURCE
from tests.test_donor_exemplars import Recording


def test_rhythm_uses_card_numbers():
    card = dict(registry.persona_for_account('en_macro').voice_card)
    card.update(sentence_length={'median': 14, 'p25': 8, 'p75': 22, 'unit': 'words'},
                post_length={'median': 180, 'p25': 90, 'p75': 300, 'unit': 'chars'},
                paragraphs={'median': 2, 'p25': 1, 'p75': 3, 'short_lines_share': .4,
                            'line_break_rate': .6}, thread_rate=.12, emoji_rate=.07,
                hooks={'question': {'share': .25}, 'claim-led': {'share': .75}})
    rhythm = voice_cards.rhythm_profile(card)
    for number in ('14', '8-22', '180', '90-300', '40%', '60%', '12%', '7%', '25%', '75%'):
        assert number in rhythm
    assert 'tendenc' in rhythm.lower()
    assert voice_cards.compact_summary(card)['rhythm'] == rhythm


def test_rhythm_fallback_samples_real_posts(tmp_path, monkeypatch):
    persona = registry.persona_for_account('en_macro')
    for i, handle in enumerate(persona.donor_weights):
        text = 'A short point about rates.\nAnother short point about liquidity.'
        (tmp_path / f'{handle.lower()}.json').write_text(json.dumps([{'id': str(i), 'text': text}]))
    monkeypatch.setattr(exemplars, 'POSTS_DIR', tmp_path)
    card = dict(persona.voice_card)
    card.pop('post_length', None)
    card.pop('paragraphs', None)
    rhythm = voice_cards.rhythm_profile(card)
    assert '100%' in rhythm
    assert str(len(text)) in rhythm
    assert 'line breaks between points' in rhythm


def donor_store(tmp_path):
    persona = registry.persona_for_account('zh_industry')
    posts = tmp_path / 'posts'; posts.mkdir()
    tags = tmp_path / 'tags'; tags.mkdir()
    for i, handle in enumerate(list(persona.donor_weights)[:5]):
        short = '供给纪律仍然关键，市场需要看资本开支指引。需求端还要等更多证据，不能仅凭一季数据下结论。'
        long = short * 12
        rows = [{'id': f'{i}-short', 'lang': 'zh', 'text': short},
                {'id': f'{i}-long', 'lang': 'zh', 'text': long}]
        (posts / f'{handle.lower()}.json').write_text(json.dumps(rows))
        (tags / f'{handle.lower()}.json').write_text(json.dumps({r['id']: {'post_type': 'data_take'} for r in rows}))
    return posts, tags


def test_compose_short_exemplars_and_all_clusters_enabled(tmp_path):
    posts, tags = donor_store(tmp_path)
    fake = Recording()
    compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take', exemplar_dir=posts, exemplar_tags_dir=tags)
    payload = json.loads(fake.messages[-1]['content'])
    assert len(payload['style_exemplars']) == 5   # 4 retrieved + 1 signature exemplar
    assert all(len(e['text']) <= 400 for e in payload['style_exemplars'])
    assert all(e['id'].endswith('short') for e in payload['style_exemplars'] if e.get('why') != 'signature exemplar')
    assert payload['persona']['voice_card']['rhythm']
    for persona in registry.load_personas().values():
        if persona.raw.get('donor_cluster'):
            assert persona.raw['exemplar_retrieval']['enabled']
            assert persona.raw['exemplar_retrieval']['k'] == 4


def test_trim_at_sentence_boundary_and_never_mid_word():
    text = 'Rates need evidence. ' + 'Liquidity is the next question. ' * 30
    trimmed = exemplars.short_text(text)
    assert len(trimmed) <= 400
    assert text.startswith(trimmed)
    assert trimmed.endswith('.')
    assert exemplars.short_text('abcdefghij ' * 60).endswith('abcdefghij')


def test_prompt_imperfection_and_variant(monkeypatch):
    assert 'Natural imperfection' in compose.COMPOSE
    for phrase in ('fragments', 'uneven sentence lengths', 'one-line paragraphs', 'casual connectors', 'rhetorical question', 'essay polish', 'symmetric paragraphs'):
        assert phrase in compose.COMPOSE
    for env, arg, expected in [('v1', None, False), ('v2', None, True), ('v2', 'v1', False), ('v1', 'v2', True)]:
        monkeypatch.setenv('VOICE_PROMPT_VARIANT', env)
        fake = Recording()
        compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take', voice_prompt_variant=arg)
        payload = json.loads(fake.messages[-1]['content'])
        assert ('short punchy hook' in payload['persona']['voice_prompt_variant']['guidance']) == expected
        if expected:
            assert '<= 12 words EN / <= 20 chars ZH' in payload['persona']['voice_prompt_variant']['guidance']
            assert 'roughly two thirds' in payload['persona']['voice_prompt_variant']['guidance']
    with pytest.raises(ValueError, match='VOICE_PROMPT_VARIANT'):
        compose.compose_source(SOURCE, 'zh_industry', Recording(), post_type='data_take', voice_prompt_variant='unknown')


def test_nearest_tagged_type_and_long_real_excerpt(tmp_path):
    persona = registry.persona_for_account('zh_industry')
    handle = next(iter(persona.donor_weights))
    text = '供给纪律仍然关键，市场需要看资本开支指引。需求端还要等更多证据，不能仅凭一季数据下结论。' * 12
    rows = [{'id': 'a', 'text': text, 'lang': 'zh'}, {'id': 'z', 'text': text, 'lang': 'zh'}]
    (tmp_path / f'{handle.lower()}.json').write_text(json.dumps(rows))
    tags = tmp_path / 'tags'; tags.mkdir()
    (tags / f'{handle.lower()}.json').write_text(json.dumps({'a': {'post_type': 'view_relay'}, 'z': {'post_type': 'earnings_take'}}))
    result = exemplars.retrieve(persona, post_type='data_take', posts_dir=tmp_path, tags_dir=tags)
    assert result[0]['id'] == 'z'  # numeric earnings take is nearest to a data take
    assert len(result[0]['text']) <= 400
    assert text.startswith(result[0]['text'])
    assert result[0]['text'].endswith('。')


@pytest.mark.parametrize('k,expected', [(1, 3), (5, 5), (9, 5)])
def test_voice_card_always_enables_exemplars_and_bounds_k(tmp_path, monkeypatch, k, expected):
    posts, tags = donor_store(tmp_path)
    persona = registry.persona_for_account('zh_industry')
    persona = replace(persona, raw={**persona.raw, 'exemplar_retrieval': {'enabled': False, 'k': k}})
    monkeypatch.setattr(compose.registry, 'persona_for_account', lambda account: persona)
    fake = Recording()
    compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take', exemplars=None,
                           exemplar_dir=posts, exemplar_tags_dir=tags)
    assert len(json.loads(fake.messages[-1]['content'])['style_exemplars']) == expected + 1   # + 1 signature exemplar


def test_body_length_follows_donor_post_lengths():
    spec = {'min': 150, 'max': 500, 'unit': 'chars'}
    card = {'post_length': {'median': 267, 'p25': 183, 'p75': 303, 'unit': 'chars'}, 'lang': 'en'}
    out = compose.body_length(spec, card, 'en')
    assert out['min'] <= 150 and out['min'] >= 60
    assert out['max'] <= 500 and out['max'] >= out['min'] + 100
    assert out['max'] < 450   # donors are short; do not invite essays
    assert 'donor' in out['note']
    assert compose.body_length(spec, None, 'en') == {'min': 150, 'max': 500}
    zh = compose.body_length(spec, {'post_length': {'median': 120, 'p25': 60, 'p75': 200}}, 'zh')
    assert zh['min'] >= 60 and zh['max'] <= 500


def test_compose_payload_and_length_check_use_donor_range(tmp_path, monkeypatch):
    persona = registry.persona_for_account('en_macro')
    card = dict(persona.voice_card, post_length={'median': 200, 'p25': 120, 'p75': 260, 'unit': 'chars'})
    persona = replace(persona, voice_card=card)
    monkeypatch.setattr(compose.registry, 'persona_for_account', lambda account: persona)
    fake = Recording()
    compose.compose_source(SOURCE, 'en_macro', fake, post_type='data_take', exemplars=False)
    rules = json.loads(fake.messages[-1]['content'])['post_type_rules']['body_length']
    assert rules['max'] < 500 and 'donor' in rules.get('note', '')
    assert 'style_exemplars' not in json.loads(fake.messages[-1]['content'])
