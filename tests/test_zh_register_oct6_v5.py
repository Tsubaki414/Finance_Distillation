"""Oct 6 v5 (PM review of v4/v4b): ZH register (研报腔), market-feeling attribution, thread padding,
batch long/short mix, revise topic gate, company IR display names, --accounts."""
import json

import pytest

from live import compose, compose_shapes as cs, qa_levels, registry, zh_register as zr
from live.exemplars import load_posts

V4B_ZH_MACRO = ('别急着押注全面宽松，货币政策仍会以流动性和结构性工具为主，年内降息降准的空间其实非常有限。'
                '尽管零售和固定资产投资等需求端数据确实在持续下滑，但人民币及汇率指数近期的走强反而削弱了央行主动出击的紧迫性。'
                '降息降准仅仅是应对增长压力进一步恶化的备用选项，而非当前的基准路径。')
V4_ZH_MACRO = '9月全票加息叠加通胀预期升到4.6%，意味着市场对后续会议继续加息的定价显然不够充分。'
V4_ZH_INDUSTRY = '举债和回报之间的缺口正在死死压缩估值溢价的生存空间，这种结构性的集中注定无法持续。'
V5_ZH_INDUSTRY = ('AI举债投资的规模早就甩开了商业回报的节奏，科技财富集中的格局根本托不住这轮估值溢价\n'
                  '这种极端的版图重构全靠预期吊着，二级市场还没给商业化落空的风险定价。')
SPOKEN = '降息这事先别想太多。\n汇率最近挺强，央行其实没那么急。\n真要降，得等数据再差一截。'


# ---------- register check ----------

@pytest.mark.parametrize('body', [V4B_ZH_MACRO, V4_ZH_MACRO, V4_ZH_INDUSTRY, V5_ZH_INDUSTRY])
def test_pm_examples_trip_zh_register(body):
    found = zr.register_findings(body)
    assert found and found[0]['code'] == 'zh_register'


def test_spoken_body_is_quiet_and_en_is_skipped():
    assert zr.register_findings(SPOKEN) == []
    assert zr.register_findings('This means the base case is structural.', 'en') == []


def test_ai_template_phrases_trip_zh_register():
    assert zr.register_findings('理由听起来很完美。\n可惜数据不配合。')
    assert zr.register_findings('这次不是需求问题，而是供给问题。')


def test_market_feeling_attribution():
    for body in ('很多人据此认为周期还长。', '市场普遍认为美联储已经停了。', '大家都觉得降息要来了。', '不少人担心存储见顶。'):
        assert zr.market_feeling_findings(body)[0]['code'] == 'market_feeling', body
    assert zr.market_feeling_findings('我觉得降息还早。\n市场定价已经很满了。') == []
    assert zr.market_feeling_findings('Many people think so.', 'en') == []


def test_density_metrics():
    d = zr.density(V4B_ZH_MACRO)
    assert d['formal_hits'] >= 4 and d['formal_per_1k'] > 20
    assert zr.density(SPOKEN)['formal_hits'] == 0


def test_new_codes_soft_with_fixes():
    for code in ('zh_register', 'market_feeling', 'thread_padding', 'revise_off_topic'):
        assert code in qa_levels.SOFT and code in qa_levels.FIXES


# ---------- real donor anchors ----------

def test_anchors_are_real_donor_lines_and_rotate():
    persona = registry.persona_for_account('zh_macro')
    a1, a2 = zr.anchors(persona, 'seed-1'), zr.anchors(persona, 'seed-2')
    if not a1:
        pytest.skip('donor posts not available')
    assert len(a1) == 4 and [x['text'] for x in a1] != [x['text'] for x in a2]
    assert len({x['handle'] for x in a1}) == 4
    for a in a1 + a2:
        texts = [p.get('text') or '' for p in load_posts(a['handle'])]
        assert any(a['text'] in t for t in texts), a        # never invented
        assert not zr.FORMAL_RX.search(a['text']) and not any(c.isdigit() for c in a['text'])
        assert not zr.MARKET_FEELING.search(a['text']) and '不是' not in a['text']


def test_system_addendum_and_stance_rule_are_chinese():
    cjk = len(zr.CJK.findall(zr.SYSTEM_ZH)) / len(zr.SYSTEM_ZH.replace(' ', ''))
    assert cjk > 0.6 and '不要逐句改写' in zr.SYSTEM_ZH and '直译' in zr.SYSTEM_ZH
    assert '35' in zr.STANCE_RULE_ZH and '意味着' in zr.STANCE_RULE_ZH


# ---------- compose integration ----------

class SeqFake:
    def __init__(self, bodies):
        from tests.test_compose import UNITS
        self.bodies, self.units, self.payloads, self.systems = list(bodies), UNITS, [], []

    def __call__(self, stage, messages, max_tokens):
        if stage == 'extract':
            return {'text': json.dumps(self.units), 'finish_reason': 'stop', 'model': 'fake'}
        self.payloads.append(json.loads(messages[-1]['content']))
        self.systems.append(' '.join(str(m.get('content')) for m in messages[:-1]))
        body = self.bodies.pop(0) if len(self.bodies) > 1 else self.bodies[0]
        ledger = [{'claim': 'x', 'unit_id': self.payloads[-1]['units'][0]['unit_id'], 'span_ref': 0}]
        return {'text': json.dumps({'body': body, 'claim_ledger': ledger}, ensure_ascii=False),
                'finish_reason': 'stop', 'model': 'fake'}


STANCE = {'decision': 'adapt', 'account_view': '存储这轮紧缺还会延续', 'supporting_unit_ids': [],
          'rationale': 'r', 'confidence': 0.6, 'view': {'subject': 'memory supply', 'direction': 'bullish'}}
FORMAL_BODY = ('存储紧缺这事还没完。\n这意味着供给端的结构性约束显然仍以产能纪律为主，而非需求驱动的基准路径。\n'
               '下游采购节奏得跟着改。')
PLAIN_BODY = '存储这轮紧缺还没完。\n厂商就是不想扩产，价格其实还在涨。\n下游采购节奏得跟着改。'


def _iso(monkeypatch, tmp_path):
    from live import anti_repeat
    monkeypatch.setattr(anti_repeat, 'HISTORY_DIR', tmp_path / 'h')
    monkeypatch.setattr(anti_repeat, 'FALLBACK_DIR', tmp_path / 'h')


def test_zh_compose_gets_chinese_system_anchors_and_register_regen(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    from tests.test_compose import SOURCE
    fake = SeqFake([FORMAL_BODY, PLAIN_BODY])
    result = compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take',
                                    stance_output=dict(STANCE), emotion_contract=False)
    assert '中文账号写法' in fake.systems[0]
    block = fake.payloads[0]['zh_register']
    assert block['rules'] and 'register_anchors' in block and block['donor_connectors'] is not None
    shown = [e.get('handle') for e in fake.payloads[0].get('style_exemplars') or []]
    assert 'overnight_clean' not in shown        # synthetic clean-prose shapes dropped
    assert result['structure_retry']['kept'] == 'retry'
    assert 'zh_register' in {f['code'] for f in result['structure_retry']['first_findings']}
    assert 'zh_register' not in {f['code'] for f in result['post_checks']}


def test_zh_register_off_switch(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    from tests.test_compose import SOURCE
    fake = SeqFake([PLAIN_BODY])
    compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take', stance_output=dict(STANCE),
                           emotion_contract=False, zh_register=False)
    assert '中文账号写法' not in fake.systems[0] and 'zh_register' not in fake.payloads[0]


def test_stance_payload_carries_zh_register_rule(monkeypatch):
    from live import stance
    seen = {}

    def fake(stage, messages, max_tokens):
        seen['payload'] = json.loads(messages[-1]['content'])
        return {'text': json.dumps({'decision': 'reject', 'account_view': '', 'supporting_unit_ids': [],
                                    'rationale': 'x', 'confidence': 0.5}), 'finish_reason': 'stop', 'model': 'f'}
    persona = registry.persona_for_account('zh_macro')
    unit = {'unit_id': 'u1', 'kind': 'view', 'statement': 'Fed done', 'source_spans': [{'exact_text': 'Fed done'}],
            'numbers': [], 'view': {'subject': 'Fed', 'direction': 'lower', 'horizon': persona.raw['stance']['horizon'],
                                    'conviction': 'medium', 'reasoning': 'Fed done', 'conditions': []}}
    stance.stance_step(unit, persona, fake)
    assert seen['payload'].get('account_view_register') == zr.STANCE_RULE_ZH


# ---------- thread shape + batch long/short mix ----------

def test_thread_needs_two_distinct_mechanisms():
    shapes = {s: 1.0 for s in cs.SHAPES}
    one = [{'kind': 'view', 'numbers': [1, 2]}, {'kind': 'fact', 'numbers': [3]}]
    assert 'short_thread' not in cs.eligible_shapes(shapes, one)
    two = one + [{'kind': 'mechanism', 'statement': 'Capex lifts networking spend', 'numbers': []},
                 {'kind': 'mechanism', 'statement': 'Memory pricing power shifts to HBM suppliers', 'numbers': []}]
    assert 'short_thread' in cs.eligible_shapes(shapes, two)
    dup = one + [{'kind': 'mechanism', 'statement': 'Capex lifts networking spend', 'numbers': []}] * 2
    assert cs.mechanism_count(dup) == 1


def test_thread_padding_detected():
    shape = {'id': 'short_thread', 'length': 'long', 'mechanisms': 1}
    body = ('网络设备这轮需求还会走强。\n\n'
            '算力之后就是网络，网络设备需求还会走强。\n\n'
            '网络设备这轮需求走强，算力之后就是网络。')
    assert cs.thread_padding_findings(body, shape)[0]['code'] == 'thread_padding'
    four = '网络需求还强。\n\n交换机订单排满。\n\n光模块也跟着涨价。\n\n明年看云厂资本开支。'
    assert cs.thread_padding_findings(four, shape)[0]['code'] == 'thread_padding'
    assert cs.thread_padding_findings(four, dict(shape, mechanisms=2)) == []
    assert cs.thread_padding_findings(four, {'id': 'take_short', 'length': 'short'}) == []


def test_batch_of_four_gets_long_and_short():
    for acc_order in (('zh_macro', 'zh_industry', 'en_macro', 'en_industry'),):
        for seed in ('a', 'b', 'c', 'd', 'e'):
            batch = []
            for acc in acc_order:
                persona = registry.persona_for_account(acc)
                units = [{'kind': 'view', 'numbers': [1]}, {'kind': 'fact', 'numbers': [2, 3]}]
                shape = cs.choose_shape(persona, units=units, batch=tuple(batch), seed=seed + acc, batch_size=4)
                batch.append({'id': shape['id'], 'length': shape['length']})
            lengths = [b['length'] for b in batch]
            assert 'long' in lengths and 'short' in lengths, (seed, batch)
            assert not any(b['id'] == 'short_thread' for b in batch)   # no mechanisms -> no thread


def test_long_variant_payload_note():
    persona = registry.persona_for_account('en_macro')
    shape = cs.choose_shape(persona, units=[{'kind': 'view', 'numbers': [1]}],
                            batch=({'id': 'take_short', 'length': 'short'},), batch_size=2, seed='x')
    assert shape['length'] == 'long' and shape.get('batch_mix')
    block = cs.payload_block(shape, 'zh', {'min': 60, 'max': 300})
    assert block['length'] == 'long' and block['length_target']['min'] >= 200
    if shape.get('length_override'):
        assert '长版' in block['structure']


def test_compose_batch_windows_of_four(monkeypatch):
    from live import compose_batch
    calls = []

    def fake_compose(source, account, client, **kw):
        calls.append((account, kw.get('shape_batch_size'), len(kw.get('shape_batch') or ())))
        return {'account_id': account, 'body': '', 'composition_shape': {'id': 'take_short', 'length': 'short'}}
    monkeypatch.setattr(compose, 'compose_source', fake_compose)
    monkeypatch.setattr(compose, 'arbitrate_batch', lambda results, mode=None: results)
    jobs = [{'account_id': f'a{i}', 'source': {}} for i in range(6)]
    compose_batch.compose_batch(jobs, None)
    assert [c[1] for c in calls] == [4, 4, 4, 4, 2, 2]
    assert [c[2] for c in calls] == [0, 1, 2, 3, 0, 1]


# ---------- ledger topic gate ----------

def test_off_topic_revise_link_is_dropped(tmp_path):
    from live.view_ledger import ViewLedger
    led = ViewLedger('zh_industry', tmp_path)
    prior = {'decision': 'adapt', 'account_view': 'AI驱动的财富集中已触及上限。', 'supporting_unit_ids': [],
             'rationale': 'r', 'confidence': 0.6,
             'view': {'subject': 'sustainability of AI-driven wealth concentration', 'direction': 'bearish',
                      'horizon': 'months', 'conviction': 'medium'}}
    led.record(led.link_continuity(prior), unit_ids=['u0'], source_ids=['s0'], draft_id='d0')
    pid = led.current()[0]['id']
    new = {'decision': 'adapt', 'account_view': 'AI基础设施需求持续压过供给。', 'supporting_unit_ids': [],
           'rationale': 'r', 'confidence': 0.6, 'revises_view_id': pid,
           'view': {'subject': 'AI基础设施需求周期', 'direction': 'bullish', 'horizon': 'months', 'conviction': 'medium'}}
    linked = led.link_continuity(new)
    assert linked['revises_view_id'] is None and linked['continuity']['dropped_revise']['view_id'] == pid
    assert led.drift_findings(linked)[0]['code'] == 'revise_off_topic'
    same = dict(new, account_view='AI财富集中还会继续。', view=dict(prior['view'], direction='bullish'))
    kept = led.link_continuity(same)
    assert kept['revises_view_id'] == pid and kept['continuity']['link'] == 'revise'


# ---------- display names + demo ----------

def test_company_ir_display_names():
    from live import attribution_frame, source_display
    for sid in ('ch062_nvidianews_nvidia_com', 'primary_nvidia'):
        tier = registry.source_licence_tier(sid)
        name = source_display.display({'source_id': sid}, 'en', tier=tier,
                                      raw_name=attribution_frame.publisher_name(sid), check_licence=False)['name']
        assert name == 'NVIDIA'
    assert source_display.display({'source_id': 'primary_amd'}, 'en', tier='A', raw_name='AMD investor relations',
                                  check_licence=False)['name'] == 'AMD'


def test_demo_accounts_option(monkeypatch, tmp_path):
    from scripts import demo_matrix_compose as demo
    seen = {}
    monkeypatch.setattr(demo, 'run', lambda out, cap, **kw: seen.update(kw) or [])
    demo.main(['--out', str(tmp_path), '--cap', '1', '--accounts', 'zh_macro,zh_industry'])
    assert seen['only_accounts'] == ['zh_macro', 'zh_industry']
    with pytest.raises(SystemExit):
        demo.main(['--out', str(tmp_path), '--accounts', 'xx'])


def test_continue_from_exclusions_accumulate(tmp_path):
    from scripts import demo_matrix_compose as demo
    a, b, c = tmp_path / 'a', tmp_path / 'b', tmp_path / 'c'
    for d, sid in ((a, 'src-a'), (b, 'src-b')):
        (d / 'drafts').mkdir(parents=True)
        (d / 'drafts' / 'x.json').write_text(json.dumps({'source': {'id': sid, 'title': sid + '-t'}}))
    assert demo.continue_batch(a, b) == {'src-a', 'src-a-t'}
    c.mkdir()
    assert demo.continue_batch(b, c) == {'src-a', 'src-a-t', 'src-b', 'src-b-t'}
