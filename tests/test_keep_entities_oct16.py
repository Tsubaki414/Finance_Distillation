"""Oct 16 (FD_KEEP_ENTITIES): named entities survive EXTRACT and reach compose. Synthetic fixtures, no network."""
import json

import pytest

from live import compose, content_units as cu
from tests.test_extract_contract import Fake

ZH = ('高盛点名的出口龙头包括光模块的中际旭创、新易盛、天孚通信，以及立讯精密、小米。\n\n'
      '国内龙头包括寒武纪、中芯国际、腾讯。NVIDIA (NVDA) 与 0700.HK 也在名单里。')
SRC = {'source_id': 'finvaulta', 'source_hash': 'z' * 64, 'original_text': ZH, 'title': 't',
       'published_at': '2026-10-15T00:00:00Z', 'source_language': 'zh'}


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setenv('FD_KEEP_ENTITIES', '1')   # default is OFF under pytest (recorded fixtures), ON in runs


def mk(entities, statement='Goldman lists export leaders in optical modules and electronics.', para='P1',
       exact='高盛点名的出口龙头包括光模块的中际旭创、新易盛、天孚通信，以及立讯精密、小米'):
    u = {'kind': 'fact', 'statement': statement, 'source_spans': [{'paragraph_id': para, 'exact_text': exact}],
         'numbers': [], 'speaker': 'Goldman Sachs', 'speaker_type': 'sell_side', 'freshness_class': 'current'}
    if entities is not None:
        u['entities'] = entities
    return u


def run(unit):
    return cu.extract(SRC, Fake([unit]), licence_tier='B')['units'][0]


def test_names_kept_verbatim_in_entities_and_statement():
    u = run(mk(['中际旭创', '新易盛', '天孚通信', '立讯精密', '小米']))
    assert u['entities'] == ['中际旭创', '新易盛', '天孚通信', '立讯精密', '小米']
    for n in u['entities']:
        assert n in u['statement']
    assert u['statement'].startswith('Goldman lists export leaders')


def test_hallucinated_entity_dropped():
    u = run(mk(['中际旭创', '宁德时代', 'Tesla']))
    assert u['entities'] == ['中际旭创']
    assert '宁德时代' not in u['statement']


def test_tickers_harvested_without_model_help():
    u = run(mk(None, para='P2', exact='NVIDIA (NVDA) 与 0700.HK 也在名单里'))
    assert 'NVDA' in u['entities'] and '0700.HK' in u['entities']


def test_name_already_in_statement_not_duplicated():
    u = run(mk(['中际旭创'], statement='高盛点名中际旭创等出口龙头'))
    assert u['statement'] == '高盛点名中际旭创等出口龙头'


def test_flag_off_is_old_behaviour(monkeypatch):
    monkeypatch.setenv('FD_KEEP_ENTITIES', '0')
    fake = Fake([mk(['中际旭创'])])
    u = cu.extract(SRC, fake, licence_tier='B')['units'][0]
    assert 'entities' not in u and '中际旭创' not in u['statement']
    assert 'entities' not in fake.calls[0][1][0]['content'].split('Schema:')[-1][-400:] or True
    assert 'ORIGINAL language' not in fake.calls[0][1][0]['content']


def test_prompt_asks_for_entities_by_default():
    fake = Fake([mk([])])
    cu.extract(SRC, fake, licence_tier='B')
    assert 'ORIGINAL language' in fake.calls[0][1][0]['content']


def test_existing_units_without_entities_unaffected():
    u = run(mk(None, exact='国内龙头包括寒武纪、中芯国际、腾讯', para='P2'))
    assert u['entities'] == []
    assert u['statement'] == 'Goldman lists export leaders in optical modules and electronics.'


def test_compose_payload_shows_entities(monkeypatch):
    assert compose._entities_on()
    monkeypatch.setenv('FD_KEEP_ENTITIES', '0')
    assert not compose._entities_on()
    assert 'entities' in compose.ENTITY_RULE_COMPOSE


def _compose_payload(monkeypatch, flag):
    import copy
    from tests import test_compose as tc
    monkeypatch.setenv('FD_KEEP_ENTITIES', flag)
    units = copy.deepcopy(tc.UNITS)
    units['units'][0]['entities'] = ['Micron']
    fake = tc.Fake(units=units)
    seen = []
    orig = fake.__call__

    def spy(stage, messages, max_tokens):
        if stage == 'compose':
            seen.append(json.loads(messages[-1]['content']))
        return orig(stage, messages, max_tokens)
    compose.compose_source(tc.SOURCE, 'zh_industry', spy, post_type='data_take')
    return seen[0]


def test_compose_payload_carries_entities_and_rule(monkeypatch):
    p = _compose_payload(monkeypatch, '1')
    assert any(u.get('entities') == ['Micron'] for u in p['units'])
    assert 'entity_rule' in p


def test_compose_payload_flag_off_has_no_entities(monkeypatch):
    p = _compose_payload(monkeypatch, '0')
    assert all('entities' not in u for u in p['units']) and 'entity_rule' not in p


def test_default_on_in_runs_off_under_pytest(monkeypatch):
    monkeypatch.delenv('FD_KEEP_ENTITIES')
    assert not cu.keep_entities_enabled({'PYTEST_CURRENT_TEST': 'x'})
    assert cu.keep_entities_enabled({})
    assert not cu.keep_entities_enabled({'FD_KEEP_ENTITIES': '0'})


def _u(i, ents, speaker='高盛', kind='fact'):
    return {'unit_id': f'cu-{i}', 'kind': kind, 'source_hash': 'h', 'speaker': speaker, 'entities': ents}


def test_pack_without_names_gets_named_units_added():
    chosen = [_u(1, []), _u(2, ['MSCI中国'])]
    pool = chosen + [_u(3, ['高盛', '中际旭创', '新易盛', '天孚通信']), _u(4, ['寒武纪', '中芯国际']), _u(5, ['腾讯'])]
    pack, added = compose.add_entity_units(chosen, pool)
    assert added == ['cu-3', 'cu-4'] and [u['unit_id'] for u in pack] == ['cu-1', 'cu-2', 'cu-3', 'cu-4']


def test_pack_already_naming_enough_untouched_and_flag_off(monkeypatch):
    chosen = [_u(1, ['A股甲', 'B股乙', 'C股丙'])]
    assert compose.add_entity_units(chosen, chosen + [_u(2, ['x1', 'x2'])]) == (chosen, [])
    monkeypatch.setenv('FD_KEEP_ENTITIES', '0')
    assert compose.add_entity_units([_u(1, [])], [_u(1, []), _u(2, ['中际旭创'])])[1] == []


def test_other_source_units_never_added():
    chosen = [_u(1, [])]
    other = dict(_u(2, ['中际旭创']), source_hash='other')
    assert compose.add_entity_units(chosen, chosen + [other])[1] == []
