import json
from dataclasses import replace
from pathlib import Path
from live import compose, registry, voice_cards as vc


def test_persona_mixes():
    for path in Path('live/personas').glob('*.json'):
        p = json.loads(path.read_text())
        if p['persona_id'] == 'en_morris_archive':
            continue
        mix = p['post_type_mix']
        assert sum(mix.get(k, 0) for k in ('judgment_take', 'contrarian_take', 'view_relay')) >= .7, path
        assert mix.get('data_take', 0) <= .1, path
        assert abs(sum(mix.values()) - 1) < 1e-9


def test_choose_data_is_last_and_positive_mix_only():
    p = replace(registry.persona_for_account('en_macro'), post_type_mix={'data_take': .9, 'mechanism_explainer': .1})
    units = [{'kind':'fact', 'usage':'paraphrase', 'numbers':[1]}, {'kind':'mechanism', 'usage':'paraphrase', 'numbers':[]}]
    types = registry.load_post_types()
    assert compose.choose(units, p, 'B', types) == 'mechanism_explainer'
    assert compose.choose(units[:1], p, 'B', types) == 'data_take'
    assert compose.choose(units[:1], replace(p, post_type_mix={'data_take':0}), 'B', types) is None


def test_variation_determinism_distribution_and_prompt():
    card = {'hooks': {'claim-led': {'share':.75}, 'question': {'share':.25}}, 'sentence_length': {'p25':10, 'median':15, 'p75':20, 'unit':'words'}}
    variants = [vc.variation_seed(card, str(i)) for i in range(200)]
    assert variants == [vc.variation_seed(card, str(i)) for i in range(200)]
    assert {v['hook'] for v in variants} == {'claim-led', 'question'}
    assert {v['length_variant'] for v in variants} == {'shorter', 'typical', 'longer'}
    assert 120 < sum(v['hook']=='claim-led' for v in variants) < 180
    assert "Lead with the account's own judgment in most posts; use at most a few numbers as support; vary hook, length and structure across posts — the tendencies describe the voice, they are not a checklist." in compose.COMPOSE


def test_compose_payload_contains_source_variation():
    from tests.test_donor_exemplars import Recording
    from tests.test_compose import SOURCE
    client = Recording()
    compose.compose_source(SOURCE, 'zh_industry', client, post_type='data_take', exemplars=False)
    payload = json.loads(client.messages[-1]['content'])['persona']
    card = registry.persona_for_account('zh_industry').voice_card
    assert payload['variation'] == vc.variation_seed(card, SOURCE['source_hash'])
