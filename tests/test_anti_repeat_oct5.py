from datetime import datetime, timezone

import pytest
from live import anti_repeat as ar, qa_levels


@pytest.fixture(autouse=True)
def history(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, 'HISTORY_DIR', tmp_path)


def codes(body, **kwargs):
    return {f['code'] for f in ar.findings(body, 'test', **kwargs)}


@pytest.mark.parametrize('phrase', ['还早着呢', '链路往下推', '真正的问题是', '这才是利润的地方',
                                     'my read is that', 'the catch?', 'supply-discipline check', 'That said,'])
def test_seed_soft(phrase):
    assert 'phrase_ban' in codes(phrase)
    assert qa_levels.level({'code': 'phrase_ban'}, frame_found=True) == 'soft'


def test_label():
    assert ar.strip_judgment_label('我的判断：利润撑不起估值。') == ('利润撑不起估值。', True)
    assert 'judgment_label' in codes('我的判断: 利润撑不起估值。')
    assert 'judgment_label' not in codes('我认为利润撑不起估值。')


def test_repeat():
    ar.record_draft('test', 'AAPL还要等待。风险不会自动消失')
    assert 'stylistic_repeat' in codes('TSLA仍有压力。风险不会自动消失')


def test_facts_not_style():
    ar.record_draft('test', 'AAPL revenue growth 12% 2026-10-05')
    assert 'stylistic_repeat' not in codes('AAPL revenue growth 12% 2026-10-05',
                                          units=[{'numbers': [{'metric': 'revenue growth'}]}])


def test_topic():
    ar.record_draft('test', '$MU pressure', meta={'subject': 'Micron'})
    assert 'duplicate_topic' in codes('$MU margins', stance={'subject': 'Micron'})
    assert 'duplicate_topic' not in codes('Update: $MU margins', stance={'subject': 'Micron'})


def test_micron_source():
    units = [{'speaker_type': 'company_exec', 'statement': 'Micron revenue guidance for Q1 is $61.5 billion',
              'numbers': [{'text': '$61.5 billion', 'metric': 'revenue guidance', 'period': 'Q1'}]}]
    assert 'verify_source' in codes('Micron guides revenue to $61.5 billion', units=units)
    assert 'verify_source' not in codes('Micron guides revenue to $6.15 billion', units=[])


def test_history_limit():
    for i in range(35):
        ar.record_draft('test', str(i))
    assert len(ar.load_recent('test')) == 30
    assert ar.load_recent('test')[-1]['text'] == '34'


def test_fallback(tmp_path, monkeypatch):
    blocked = tmp_path / 'blocked'
    blocked.write_text('file')
    monkeypatch.setattr(ar, 'HISTORY_DIR', blocked)
    monkeypatch.setattr(ar, 'FALLBACK_DIR', tmp_path / 'fallback')
    assert ar.record_draft('test', 'body')
    assert ar.load_recent('test')[0]['text'] == 'body'


def test_compose_label_retries_once_and_strips():
    from tests.test_compose import Fake, GOOD_BODY, run
    result, fake = run(Fake(body='我的判断：' + GOOD_BODY), post_type='data_take')
    assert result['anti_repeat_retry']['attempted']
    assert '我的判断' not in result['body']
    assert 'judgment_label' in {f['code'] for f in result['post_checks']}
    assert ar.load_recent('zh_industry')[-1]['text'] == result['body']


def test_morris_archive_loading(tmp_path, monkeypatch):
    import json
    from live import exemplars
    p = tmp_path / 'sources.json'
    p.write_text(json.dumps({'sources': [{'source': {'id': 'a', 'original_text': '风险管理比预测更重要。' * 8,
                                                     'en_text': 'Risk management matters more than prediction. ' * 3}}]}))
    monkeypatch.setattr(exemplars, 'MORRIS_PATHS', (p, tmp_path / 'missing'))
    posts = exemplars.load_morris_posts()
    assert posts[0]['lang'] == 'en'
    assert posts[0]['handle'] == 'Morris_LT'


def test_morris_untagged_units():
    from live.retrieval import units_for_persona
    class Store:
        def units(self):
            return [{'unit_id': 'm', 'source': {'source_id': 'x_Morris_LT'}, 'unit': {}}]
    assert units_for_persona(Store(), 'investing_philosophy')[0]['unit_id'] == 'm'


def test_posting_habits_default(monkeypatch):
    from live import posting_habits, registry
    monkeypatch.setattr(posting_habits, 'load_posts', lambda *a: [])
    card = posting_habits.build_card(registry.load_personas()['investing_philosophy'])
    assert 'Fiona' in card['basis']
    assert sum(card['length_mix'].values()) == 1
    assert card['sample_ids'] == []


def test_topic_expired():
    ar.record_draft('test', '$MU pressure', meta={'subject': 'Micron'})
    from datetime import timedelta
    assert 'duplicate_topic' not in codes('$MU margins', stance={'subject': 'Micron'},
                                          now=datetime.now(timezone.utc) + timedelta(hours=37))


def test_compose_retry_keeps_valid_original_on_provider_error():
    from tests.test_compose import Fake, GOOD_BODY, run
    class FailingRepair(Fake):
        def __call__(self, stage, messages, max_tokens):
            if self.calls.count('compose') >= 1 and stage == 'compose':
                raise ValueError('offline repair unavailable')
            return super().__call__(stage, messages, max_tokens)
    result, _ = run(FailingRepair(body='我的判断：' + GOOD_BODY), post_type='data_take')
    assert result['anti_repeat_retry']['kept'] == 'original'
    assert result['body'] == GOOD_BODY


def test_morris_merge_opt_in(monkeypatch):
    from dataclasses import replace
    from live import exemplars, registry
    persona = registry.load_personas()['investing_philosophy']
    monkeypatch.setattr(exemplars, 'load_posts', lambda *a: [])
    monkeypatch.setattr(exemplars, 'load_morris_posts', lambda: [
        {'handle': 'Morris_LT', 'id': 'z', 'text': '用风险管理代替赌性。', 'lang': 'zh'}])
    assert len(exemplars.retrieve(persona)) == 1
    raw = {**persona.raw, 'exemplar_retrieval': {'include_morris': False}}
    assert exemplars.retrieve(replace(persona, raw=raw)) == []
