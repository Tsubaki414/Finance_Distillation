"""Oct 6 v4 (PM review of v3): composition shapes, number runs, coherence, footer, number rebinding, freshness."""
import json
import pytest

from live import attribution_frame, compose, compose_shapes as cs, coherence, qa_levels, registry
from scripts import demo_matrix_compose as demo

V3 = {
    'zh_industry': ('警惕低杠杆假象，表外租约不缩减，云厂商信用利差就难降\n\n截至二季度财报季，超大规模科技公司的租赁承诺达到1.5万亿美元\n\n'
                    '其中1.0万亿美元是尚未开始执行的租约，完全没进资产负债表\n\n若将这些表外承诺计入企业价值，估值倍数会上调35%\n\n'
                    '除非表外租约规模实质性缩减，否则额外的利差风险溢价很难消除。'),
    'en_macro': ("The Fed is likely done after a December hike, provided underlying momentum in inflation doesn't re-accelerate.\n"
                 "August core PCE printed soft at 0.25% mom\nWith 10-year yields sitting at 5.28%, the long end is already doing the tightening\n"
                 "I do think they pause here if soft data keeps printing."),
    'en_industry': ("IMO the dream of multiple suppliers is premature—Nvidia's rack-scale moat is locked until a rival ships a turnkey stack.\n\n"
                    "The NVL72 rack packs 72 GPUs and 36 CPUs into a system that just works out of the box\n\n"
                    "That shift only deepens the switching cost for software teams\n\n"
                    "The narrative only flips if we see a rival capture actual inference procurement volume with a fully integrated rack."),
}


# ---------- shapes: catalogue, donor derivation, rotation ----------

def test_only_short_thread_ends_on_falsifier():
    assert [s for s, spec in cs.SHAPES.items() if spec['ending'] == cs.FALSIFIER] == ['short_thread']
    assert cs.SHAPES['data_punch']['max_number_lines'] == 3
    # Oct 10 nat3: short_list also allows 3 number lines (a list of facts)
    assert all(spec['max_number_lines'] <= 2 for s, spec in cs.SHAPES.items()
               if s not in ('data_punch', 'short_list'))


def test_persona_shapes_follow_donor_closings_and_length_mix():
    zh = cs.persona_shapes(registry.persona_for_account('zh_macro'))
    en = cs.persona_shapes(registry.persona_for_account('en_macro'))
    assert 'contrarian_question' not in zh            # no question closing among zh_macro donors
    assert 'contrarian_question' in en                # en_macro donors close on open questions
    assert zh['take_short'] > zh['short_thread']      # zh_macro donors: 68% short posts


def test_rotation_never_repeats_last_shape_and_alternates_length():
    persona = registry.persona_for_account('en_industry')
    recent, seq = [], []
    for i in range(8):
        shape = cs.choose_shape(persona, units=[{'numbers': [1, 2, 3]}], recent=recent, seed=str(i))
        seq.append(shape['id'])
        recent.append({'text': 'x', 'shape': shape['id']})
    assert all(a != b for a, b in zip(seq, seq[1:]))
    lengths = [cs.SHAPES[s]['length'] for s in seq]
    assert sum(a == b for a, b in zip(lengths, lengths[1:])) <= 2
    endings = [cs.SHAPES[s]['ending'] for s in seq]
    assert endings.count(cs.FALSIFIER) <= 2
    assert all(not (a == b == cs.FALSIFIER) for a, b in zip(endings, endings[1:]))


def test_batch_shapes_are_excluded():
    persona = registry.persona_for_account('zh_industry')
    used = []
    for _ in range(4):
        used.append(cs.choose_shape(persona, units=[{'numbers': [1, 2]}], batch=tuple(used), seed='s')['id'])
    assert len(set(used)) == 4


def test_number_poor_pack_skips_number_shapes():
    persona = registry.persona_for_account('zh_macro')
    shape = cs.choose_shape(persona, units=[{'numbers': []}], seed='a')
    assert shape['id'] not in ('data_punch', 'one_number_punch')


def test_payload_block_has_length_band_and_ending_rule():
    block = cs.payload_block({'id': 'take_short'}, 'zh', {'min': 100, 'max': 400})
    assert block['max_numbers'] == 0 and block['length_target']['max'] <= 205
    assert '只要' in block['ending_rule'] and 'line 1' in block['line1_rule'].lower()


# ---------- skeleton / soft checks on the real v3 drafts ----------

def test_v3_skeleton_is_detected():
    for body in V3.values():
        sk = cs.skeleton(body)
        assert sk['opener'] == 'conditional' and sk['ending'] == cs.FALSIFIER
    rows = [{'account_id': a, 'body': b} for a, b in V3.items()]
    cs.batch_findings(rows)
    flagged = [r['account_id'] for r in rows if any(f['code'] == 'structure_repeat' for f in r.get('post_checks', []))]
    assert flagged == ['en_macro', 'en_industry']   # 2nd and 3rd falsifier endings in the batch


def test_batch_findings_quiet_for_distinct_shapes():
    rows = [{'account_id': 'a', 'body': '联储这轮还没完。数据不支持停手。', 'composition_shape': {'id': 'take_short'}},
            {'account_id': 'b', 'body': 'Hikes are not done.\nCore PCE 0.25% mom says so.\nWho is still pricing cuts?',
             'composition_shape': {'id': 'contrarian_question'}}]
    cs.batch_findings(rows)
    assert all(not r.get('post_checks') for r in rows)


def test_history_structure_repeat():
    recent = [{'text': 'Call.\nData 1.\nIt flips if X.', 'shape': 'short_thread'}]
    found = cs.history_findings('Call two.\nData 2.\nThis breaks only if Y.', recent, shape={'id': 'short_thread'})
    codes = [f['detail'] for f in found]
    assert any('falsifier ending again' in d for d in codes) and any('same composition shape' in d for d in codes)


def test_number_run_flags_three_number_lines_unless_data_punch():
    assert [f['code'] for f in cs.number_run_findings(V3['zh_industry'])] == ['number_run']
    assert cs.number_run_findings(V3['zh_industry'], 'data_punch') == []
    assert cs.number_run_findings(V3['en_macro']) == []


def test_shape_mismatch_conditional_ending_and_opener():
    found = cs.shape_findings(V3['en_industry'], {'id': 'take_short', 'ending': cs.VERDICT, 'max_number_lines': 0})
    details = ' '.join(f['detail'] for f in found)
    assert 'conditional ending' in details and 'line 1 carries a condition' in details
    assert cs.shape_findings('Nvidia keeps the rack.\nNobody ships a turnkey stack yet.',
                             {'id': 'take_short', 'ending': cs.VERDICT, 'max_number_lines': 0}) == []


# ---------- internal coherence ----------

def test_internal_contradiction_v3_en_macro():
    found = coherence.internal_contradiction_findings(V3['en_macro'])
    assert [f['code'] for f in found] == ['internal_contradiction']
    assert 'pause here' in found[0]['detail']


@pytest.mark.parametrize('body', [
    'The Fed is done after one more hike in December. Soft data keeps that hike on the table.',
    'I am not bearish here. Bullish on the memory cycle into 2027.',
    '联储再加一次息后就会停。12月这次加息仍会落地。',
])
def test_coherent_bodies_not_flagged(body):
    assert coherence.internal_contradiction_findings(body) == []


def test_direction_contradiction_flagged():
    assert coherence.internal_contradiction_findings('我看多美光。但这里我看空存储。')[0]['code'] == 'internal_contradiction'


def test_new_codes_are_soft_with_fixes():
    for code in ('structure_repeat', 'shape_mismatch', 'number_run', 'internal_contradiction', 'hedged_opener'):
        assert code in qa_levels.SOFT and code in qa_levels.FIXES


def test_prompts_carry_shape_and_coherence_rules():
    assert 'composition_shape, when supplied, is HARD' in compose.COMPOSE
    assert 'Coherence: every line must agree with line 1' in compose.COMPOSE
    assert 'concrete falsifier' not in compose.COMPOSE
    from live import stance
    assert 'Do NOT pack the trigger / falsifier into account_view' in stance.STANCE
    assert 'prefer a concrete falsifiable call' not in stance.STANCE


# ---------- footer credit ----------

def test_generic_sell_side_footer_is_neutral_reference():
    source = {'id': 'r1', 'source_id': 'reportgem_goldman_sachs', 'adapter': 'reportgem', 'publisher': 'Goldman Sachs'}
    en = attribution_frame.render('judgment_take', source, lang='en')
    zh = attribution_frame.render('judgment_take', source, lang='zh')
    assert en['text'] == '\n\n(ref: sell-side research)' and 'Goldman' not in en['text']
    assert zh['text'] == '（参考：券商研报）'
    named = attribution_frame.render('judgment_take', {'id': 'c', 'source_id': 'chipstrat', 'publisher': 'Chipstrat'}, lang='en')
    assert named['text'] == '\n\nSource: Chipstrat'


# ---------- number rebinding ----------

def test_number_rebinding_uses_full_evidence_text():
    units = [{'source_spans': [{'exact_text': 'a rack with 72 GPUs in it'}], 'statement': 'x'}]
    source = {'original_text': 'make sure it works across 72 GPUs and 36 CPUs; 1.0万亿美元来自尚未开始执行的租约'}
    text = compose._evidence_text(units, source)
    assert compose._number_in_text('72', text) and compose._number_in_text('36', text)
    assert compose._number_in_text('$1.0', text)
    assert not compose._number_in_text('48', text)
    # v4 zh_macro: reasoning "10月" from an English "October" span is a month, not an unbound metric
    assert compose._number_in_text('10', 'raise the probability of an October or December move')
    assert not compose._number_in_text('11', 'raise the probability of an October or December move')


# ---------- freshness in selection ----------

def _rec(source, kind, published, adapter='newsletter'):
    return {'unit_id': f'{source}-{kind}', 'licence_tier': 'A',
            'source': {'source_hash': source, 'id': source, 'adapter': adapter, 'source_id': 'nl-' + source,
                       'published_at': published, 'title': 'T', 'source_language': 'en'},
            'unit': {'kind': kind, 'as_of': published[:10], 'published_at': published, 'source_spans': []}}


def test_selection_prefers_fresh_source(monkeypatch):
    monkeypatch.setattr(demo, 'has_valid_view', lambda unit: unit.get('kind') == 'view')
    from live import freshness
    monkeypatch.setattr(freshness, 'today', lambda: __import__('datetime').date(2026, 10, 6))
    old = [_rec('old', 'view', '2026-09-17T00:00:00Z'), _rec('old', 'fact', '2026-09-17T00:00:00Z')]
    new = [_rec('new', 'view', '2026-10-05T00:00:00Z'), _rec('new', 'fact', '2026-10-05T00:00:00Z')]
    monkeypatch.setattr(demo, 'units_for_persona', lambda store, account, **_k: old + new)
    sel = {}
    chosen = demo.select_groups(object(), ['en_industry'], sel)
    assert {r['source']['id'] for r in chosen['en_industry']} == {'new'}
    assert demo.group_freshness(old) < demo.group_freshness(new) == 1.0


# ---------- compose integration (offline fake client) ----------

class SeqFake:
    """Extract -> UNITS; compose calls return the queued bodies in order (last one repeats)."""
    def __init__(self, bodies):
        from tests.test_compose import UNITS
        self.bodies, self.units, self.payloads = list(bodies), UNITS, []

    def __call__(self, stage, messages, max_tokens):
        if stage == 'extract':
            return {'text': json.dumps(self.units), 'finish_reason': 'stop', 'model': 'fake'}
        payload = json.loads(messages[-1]['content'])
        self.payloads.append(payload)
        body = self.bodies.pop(0) if len(self.bodies) > 1 else self.bodies[0]
        ledger = [{'claim': 'x', 'unit_id': payload['units'][0]['unit_id'], 'span_ref': 0}]
        return {'text': json.dumps({'body': body, 'claim_ledger': ledger}, ensure_ascii=False),
                'finish_reason': 'stop', 'model': 'fake'}


STANCE = {'decision': 'adapt', 'account_view': '存储这轮紧缺还会延续', 'supporting_unit_ids': [],
          'rationale': 'r', 'confidence': 0.6, 'view': {'subject': 'memory supply', 'direction': 'bullish'}}
PAD = '晶圆厂建设周期长，价格还在涨，厂商没有扩产冲动，供给端的克制会延续下去，下游买家得按更长的紧缺期安排采购和库存。'
BAD = '我看多存储这一轮。\n' + PAD + '\n不过这里我看空存储。'
GOOD = '存储这轮紧缺还没完。\n' + PAD + '\n下游的采购节奏得跟着改。'


def _iso(monkeypatch, tmp_path):
    from live import anti_repeat
    monkeypatch.setattr(anti_repeat, 'HISTORY_DIR', tmp_path / 'h')
    monkeypatch.setattr(anti_repeat, 'FALLBACK_DIR', tmp_path / 'h')


def test_compose_sends_shape_records_history_and_repairs_contradiction(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    from tests.test_compose import SOURCE
    fake = SeqFake([BAD, GOOD])
    result = compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take',
                                    stance_output=dict(STANCE), emotion_contract=False)
    shape = fake.payloads[0]['composition_shape']
    assert shape['id'] in cs.SHAPES and shape['ending_rule'] and shape['line1_rule']
    assert result['composition_shape']['id'] == shape['id']
    assert result['structure_retry']['kept'] == 'retry'
    assert 'coherence_repair' in result['structure_retry']['rewrite_note']
    assert 'internal_contradiction' not in {f['code'] for f in result['post_checks']}
    from live import anti_repeat
    row = anti_repeat.load_recent(registry.persona_for_account('zh_industry').persona_id)[-1]
    assert row['shape'] == shape['id'] and row['skeleton']['ending'] in ('other', 'question', 'falsifier')
    # next compose for the same persona avoids the previous shape; the batch excludes another one
    fake2 = SeqFake([GOOD])
    other = [s for s in cs.SHAPES if s != shape['id']][0]
    compose.compose_source(SOURCE, 'zh_industry', fake2, post_type='data_take', stance_output=dict(STANCE),
                           emotion_contract=False, shape_batch=(other,))
    assert fake2.payloads[0]['composition_shape']['id'] not in (shape['id'], other)


def test_shapes_off_switch(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    from tests.test_compose import SOURCE
    fake = SeqFake([GOOD])
    result = compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take',
                                    stance_output=dict(STANCE), emotion_contract=False, composition_shapes=False)
    assert 'composition_shape' not in fake.payloads[0] and 'composition_shape' not in result


def test_hedged_opener_soft():
    assert cs.hedged_opener_findings('我个人觉得，别急着给这轮紧缩周期画句号。')[0]['code'] == 'hedged_opener'
    assert cs.hedged_opener_findings("IMO the dream of multiple suppliers is premature.")
    assert cs.hedged_opener_findings('别急着画句号。\n我觉得数据还不够。') == []
    assert 'hedged_opener' in qa_levels.SOFT and 'hedged_opener' in qa_levels.FIXES


def test_opener_lexeme_repeat_in_history():
    recent = [{'text': '我个人觉得，别急着给这轮紧缩画句号。'}, {'text': '别急，若新订单跌破临界点…'}]
    found = cs.history_findings('别急着押注全面宽松，政策仍以结构性工具为主。', recent)
    assert any('same opener "别急"' in f['detail'] for f in found)
    assert cs.history_findings('货币政策仍以结构性工具为主。', recent) == []


def test_mid_required_effect_has_no_example_lexemes():
    from live import emotion_contract as ec
    assert not any(w in ec.REQUIRED_EFFECT['mid'] for w in ('别急', '怀疑', '警惕', '未必'))


def test_signature_quote_copy_is_flagged():
    from live import exemplars
    closing = '从个案上升到方法论：「坐办公室看数据和跑一趟供应链看到的东西不一样。」'
    body = '坐办公室看总量数据和跑一趟供应链看到的东西不一样\n如果溢价守不住，这个周期就难以成立。'
    assert exemplars.copied_phrases(body, [closing])[0]['code'] == 'exemplar_phrase_copied'
