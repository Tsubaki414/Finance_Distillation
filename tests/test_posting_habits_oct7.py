"""Oct 7 posting habits from the donor cluster: post-type / length sampling per post, compose wiring. Fakes only."""
import collections
import json
from datetime import date

from live import compose, posting_habits as ph, registry
from tests.test_zhfix_oct6_v11 import JudgmentFake, NOW, POOL, SOURCE, _iso


def _p(text, **kw):
    return {'id': kw.pop('id', '2106545437817897279'), 'text': text, **kw}


def test_capped_weights_cap_and_sum():
    w = ph.capped_weights({'a': 0.7, 'b': 0.2, 'c': 0.1})
    assert abs(sum(w.values()) - 1) < 1e-3 and w['a'] <= ph.DONOR_CAP + 1e-6
    assert w['b'] > 0.2 and w['c'] > 0.1                              # excess spread over the others
    assert ph.capped_weights({'a': 1.0}) == {'a': 1.0}                 # a single donor cannot be capped


def test_classify_types_and_buckets():
    assert ph.classify(_p('美债收益率又上去了'), 'zh')[:2] == ('one_liner', 'short')
    assert ph.classify(_p('1/5 Why the Fed pauses\nfirst point here'), 'en')[0] == 'thread'
    assert ph.classify(_p('1/5 Why the Fed pauses'), 'en')[2] == 5
    assert ph.classify(_p('Big week:\n- CPI 3.1%\n- PPI 2.4%\n- Retail sales 0.6%'), 'en')[0] == 'list_dump'
    assert ph.classify(_p('降息落地了。\n谁还会接这么长的久期？'), 'zh')[0] == 'question'
    assert ph.classify(_p('同意，这才是关键', quote=True), 'zh')[0] == 'quote_comment'
    assert ph.classify(_p('Breadth just rolled over', media=['photo']), 'en')[0] == 'chart_caption'
    assert ph.classify(_p('BREAKING: Fed holds rates steady'), 'en')[0] == 'news_flash'
    assert ph.classify(_p('x' * 500), 'en')[:2] == ('long_take', 'long')
    old_link = _p('Read the full report here https://t.co/abc', restored_from='jev_tag_request')
    assert ph.classify(old_link, 'en')[0] != 'chart_caption'           # a link share is not an image post


def test_post_time_from_snowflake_id():
    t = ph.post_time({'id': '2106545437817897279'})
    assert t.year == 2026 and t.month == 10


def _card():
    return {'persona_id': 'zh_macro', 'version': ph.CARD_VERSION,
            'post_type_mix': {'one_liner': 0.3, 'long_take': 0.3, 'quick_take': 0.4},
            'length_by_type': {'one_liner': {'short': 1.0}, 'long_take': {'long': 1.0},
                               'quick_take': {'short': 0.5, 'medium': 0.5}}}


def test_choose_format_samples_length_per_post_not_average():
    persona = registry.persona_for_account('zh_macro')
    picks = [ph.choose_format(persona, seed=f's{i}', card=_card()) for i in range(300)]
    lengths = collections.Counter(p['length'] for p in picks)
    assert lengths['short'] > 60 and lengths['long'] > 60 and lengths['medium'] > 20   # a mix, not one band
    assert all(p['length'] == 'long' for p in picks if p['type'] == 'long_take')
    assert ph.choose_format(persona, seed='x', card=_card()) == ph.choose_format(persona, seed='x', card=_card())


def test_rotation_downweights_types_of_last_three_posts():
    persona = registry.persona_for_account('zh_macro')
    recent = [{'post_format': 'quick_take'}, {'post_format': 'long_take'}, {'post_format': 'quick_take'}]
    picks = collections.Counter(ph.choose_format(persona, seed=f's{i}', card=_card(), recent=recent)['type']
                                for i in range(200))
    assert picks['one_liner'] > 150


def test_cards_are_cluster_built_aggregates_only():
    for pid, persona in registry.load_personas().items():
        if not persona.donor_weights:
            continue
        card = json.loads((ph.CARDS_DIR / f'{pid}.json').read_text())
        assert card['version'] == ph.CARD_VERSION and set(card['donors']) == set(persona.donor_weights)
        assert abs(sum(card['post_type_mix'].values()) - 1) < 0.01
        assert max(v['weight_capped'] for v in card['donors'].values()) <= ph.DONOR_CAP + 1e-6
        assert 'text' not in json.dumps(card['per_type_habits'])          # no donor text in git


def test_sample_post_time_inside_hours_and_spaced():
    card = {'persona_id': 'x', 'posting_hours_london': {'9': 0.5, '14': 0.5}}
    t1 = ph.sample_post_time(card, date(2026, 10, 7), seed='a')
    t2 = ph.sample_post_time(card, date(2026, 10, 7), seed='b', taken=[t1])
    assert t1.hour in (9, 14) and abs((t2 - t1).total_seconds()) >= 20 * 60


class CaptionFake(JudgmentFake):
    def __call__(self, stage, messages, max_tokens):
        out = super().__call__(stage, messages, max_tokens)
        if stage == 'compose':
            v = json.loads(out['text'])
            v['image_needed'] = '美国非农新增就业，近12个月柱状图，标出9月'
            out['text'] = json.dumps(v, ensure_ascii=False)
        return out


def test_compose_uses_sampled_format_with_anchors_and_image_needed(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    fake = CaptionFake(body='9月就业只增2.9万，美联储没理由再急着加息')
    fmt = {'type': 'chart_caption', 'length': 'short'}
    result = compose.compose_source(SOURCE, 'zh_macro', fake, post_type='judgment_take',
                                    extracted_units=[dict(u) for u in POOL], exemplars=False, emotion_contract=False,
                                    now=NOW, post_format=fmt)
    payload = fake.payloads['compose'][0]
    block = payload['post_format']
    assert block['type'] == 'chart_caption' and 'image_needed_rule' in block and len(block['anchor_posts']) <= 2
    assert payload['composition_shape']['id'] in ph.TYPE_SHAPES['chart_caption']
    assert payload['composition_shape']['length_target'] == {'min': 8, 'max': 80}
    assert result['post_format']['type'] == 'chart_caption'
    assert result['image_needed'].startswith('美国非农')
    assert 'post_format' in fake.systems['compose'][0]
    # compact type: no separate so-what line is asked for
    assert not [f for f in result['post_checks'] if f['code'] == 'missing_implication']
    from live import anti_repeat
    assert anti_repeat.load_recent('zh_macro')[-1]['post_format'] == 'chart_caption'


def test_compose_thread_parts_and_format_off_switch(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    body = '美联储暂时不急着再加息。\n\n因为9月新增就业只有2.9万。\n\n10月加息的概率已经掉到22%。'
    fake = JudgmentFake(body=body)
    result = compose.compose_source(SOURCE, 'zh_macro', fake, post_type='judgment_take',
                                    extracted_units=[dict(u) for u in POOL], exemplars=False, emotion_contract=False,
                                    now=NOW, post_format={'type': 'thread', 'length': 'thread', 'thread_parts': 3})
    assert len(result['thread']) == 3 and result['thread'][0].startswith('美联储')
    off = compose.compose_source(SOURCE, 'zh_macro', JudgmentFake(), post_type='judgment_take',
                                 extracted_units=[dict(u) for u in POOL], exemplars=False, emotion_contract=False, now=NOW)
    assert 'post_format' not in off      # fixture mode (emotion_contract=False) keeps the recorded payload
