"""Oct 6 zh_native (Fiona on demo_matrix_oct6_zhfix2 drafts 2-5): 其实 / 这意味着 in nearly every draft,
翻译腔 (「AI发行人的表外租赁负债」, long nominal phrases) and Bowman's speech written as 「我认为…我们能看到…」.
Chinese sources compose from their own Chinese sentences; three soft checks join the one structure regen.
Fakes only - no model calls."""
import json

from live import compose, compose_shapes as cs, qa_levels, stance as stance_mod, zh_register as zr
from tests.test_zhfix_oct6_v11 import NOW, POOL, SOURCE, JudgmentFake, _iso, _u, WILLIAMS

# zhfix2 draft 5 (fed-bowman20261001a) and its first-person English span.
BOWMAN_BODY = ('我认为eSLR重新校准后，国债市场的运作和流动性确实已经出现了明显的改善。我们能看到买卖价差在收窄。\n\n'
               '交易商的国债总持仓从大约6000亿美元增加到了7000多亿美元。')
BOWMAN_UNIT = {**_u('cu-bow', 'view', 'The eSLR recalibration has improved Treasury market functioning.',
                    speaker='Michelle W. Bowman'), 'speaker_type': 'official'}
BOWMAN_UNIT['source_spans'] = [{'paragraph_id': 'P1', 'exact_text': 'We can already see improved market liquidity '
                                                                      'and functioning across these markets.'}]

ZH_SPAN = '据高盛信贷策略师于8月发布的研究，截至二季度财报季，超大规模科技公司合计追踪到1.5万亿美元的租赁承诺。'


def test_zh_original_only_for_chinese_spans():
    zh = {'source_spans': [{'exact_text': ZH_SPAN}]}
    assert zr.zh_original(zh) == ZH_SPAN
    assert zr.zh_original({'source_spans': [ZH_SPAN]}) == ZH_SPAN          # compose payload form (strings)
    assert zr.zh_original(POOL[3]) == ''                                    # English source
    assert zr.zh_original({'source_spans': [{'exact_text': 'Meta 35%'}]}) == ''


def _zh_pool():
    pool = [dict(u) for u in POOL]
    for u in pool:
        if u['unit_id'] == 'cu-jobs':
            u['source_spans'] = [{'paragraph_id': 'P1', 'exact_text': '美国9月新增非农就业2.9万人，远低于预期的8.4万人，失业率升至4.2%。'}]
    return pool


def test_chinese_source_units_use_the_original_not_a_back_translation(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    fake = JudgmentFake({'why_unit_ids': ['cu-jobs'], 'so_what_unit_ids': ['cu-odds'],
                         'zh_units': {'cu-jobs': '美国经济9月增加了29,000个工作岗位的就业。',
                                      'cu-odds': '截至周五下午，联邦基金期货显示10月加息概率为22%，周一时为66%。'}})
    compose.compose_source(SOURCE, 'zh_macro', fake, post_type='judgment_take', extracted_units=_zh_pool(),
                           exemplars=False, emotion_contract=False, now=NOW)
    ctx = {u['unit_id']: u for u in fake.payloads['stance'][0]['context_units']}
    assert ctx['cu-jobs']['source_zh'].startswith('美国9月新增非农') and 'source_zh' not in ctx['cu-odds']
    assert 'source_zh' in stance_mod.ZH_UNITS_RULE and '鲍曼认为' in stance_mod.ZH_UNITS_RULE
    units = {u['unit_id']: u for u in fake.payloads['compose'][0]['units']}
    assert units['cu-jobs']['statement'].startswith('美国9月新增非农')           # original Chinese, not zh_units
    assert units['cu-jobs']['statement_origin'] == 'source_zh'
    assert units['cu-jobs']['statement_en'].startswith('The US economy added 29,000')
    assert units['cu-odds']['statement'].startswith('截至周五下午') and 'statement_origin' not in units['cu-odds']
    system = fake.systems['compose'][0]
    assert 'source_zh' in system and '不要翻译' in system and 'register_anchors' in system


def test_en_stance_has_no_source_zh(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    fake = JudgmentFake()
    compose.compose_source(SOURCE, 'en_macro', fake, post_type='judgment_take', extracted_units=_zh_pool(),
                           exemplars=False, emotion_contract=False, now=NOW)
    assert not any('source_zh' in u for u in fake.payloads['stance'][0].get('context_units', []))


def test_translationese_check():
    det = zr.translationese_findings('超大规模科技公司的表外的租赁的负债会压着利差。')[0]['detail']
    assert '的' in det
    assert '翻译式名词化' in zr.translationese_findings('流动性出现了明显的改善。')[0]['detail']
    assert '被' in zr.translationese_findings('利率被压低，股价被拖累。')[0]['detail']
    assert zr.translationese_findings('美联储12月之后先停。\n9月非农只加了2.9万人，就业撑不住再加息。') == []
    assert zr.translationese_findings('利润被拖累了一个季度。') == []          # one 被 is ordinary Chinese


def test_speaker_first_person_check():
    ledger = [{'claim': '我认为eSLR重新校准后，国债市场的运作和流动性确实已经出现了明显的改善', 'unit_id': 'cu-bow', 'span_ref': 0}]
    det = zr.speaker_voice_findings(BOWMAN_BODY, [BOWMAN_UNIT], ledger)[0]['detail']
    assert '我们' in det and '我认为' in det
    third = '鲍曼的意思是，eSLR调完之后国债市场顺畅多了。\n买卖价差收窄了。'
    assert zr.speaker_voice_findings(third, [BOWMAN_UNIT], [{'claim': third, 'unit_id': 'cu-bow', 'span_ref': 0}]) == []
    # the account's own opinion on another unit is fine
    own = '鲍曼说价差收窄了。我认为短债会先受益。'
    assert zr.speaker_voice_findings(own, [BOWMAN_UNIT], [{'claim': '我认为短债会先受益', 'unit_id': 'cu-x', 'span_ref': 0}]) == []
    assert '第三人称' in zr.SYSTEM_ZH and '我们能看到' in zr.SYSTEM_ZH


def test_connective_repeat_within_draft_and_across_last_five():
    assert zr.connective_repeat_findings('其实利差会走阔。其实没人定价。')[0]['detail'].startswith('同一篇')
    recent = ['A其实B。', '无。', '无。', '无。']
    assert '其实' in zr.connective_repeat_findings('这事其实不难。', recent)[0]['detail']
    old = ['A其实B。', '无。', '无。', '无。', '无。']                       # 其实 is 5 drafts back: outside the window
    assert zr.connective_repeat_findings('这事其实不难。', old) == []
    assert '这意味着' in zr.connective_repeat_findings('意味着利差走阔。', ['这意味着估值更贵。'])[0]['detail']
    assert zr.connective_repeat_findings('因为就业弱，所以先停。', ['所以利差走阔。']) == []   # plain grammar
    assert zr.recent_connectives(['这其实不难', '这意味着贵']) == ['其实', '这意味着']


def test_new_codes_soft_with_fixes_and_in_structure_regen():
    for code in ('zh_translationese', 'speaker_first_person', 'connective_repeat'):
        assert qa_levels.level({'code': code}, frame_found=False) == 'soft'
        assert code in qa_levels.FIXES


def test_no_required_connective_in_prompts():
    for text in (zr.SYSTEM_ZH, ' '.join(zr.RULES_ZH), *[spec['zh'] for spec in cs.SHAPES.values()]):
        assert '意味着什么' not in text
    rule4 = next(line for line in zr.SYSTEM_ZH.splitlines() if line.startswith('4.'))
    assert '没有哪个连接词是必须的' in rule4
    block = cs.payload_block({'id': 'one_number_punch', **{k: cs.SHAPES['one_number_punch'][k] for k in
                                                          ('length', 'max_numbers', 'max_number_lines', 'ending', 'line_breaks')}},
                             'zh', {'min': 80, 'max': 300})
    assert '这意味着' in block['ending_rule'] and '不要固定' in block['ending_rule']
    assert '不是X，而是Y' in compose.COMPOSE and '「不是X，而是Y」' in zr.SYSTEM_ZH        # still banned


class SpeakerFake(JudgmentFake):
    """First compose writes Bowman's 我们 / connective twice; the structure regen writes it in third person."""

    def __call__(self, stage, messages, max_tokens):
        out = super().__call__(stage, messages, max_tokens)
        if stage == 'compose':
            v = json.loads(out['text'])
            n = len(self.payloads['compose'])
            v['body'] = ('美联储暂时不急着再加息。\n我们能看到9月新增就业只有2.9万，其实远低于预期。\n其实10月加息的概率已经掉到22%，短债先松口气。'
                         if n == 1 else
                         '美联储暂时不急着再加息。\n因为9月新增就业只有2.9万，远低于预期。\n10月加息的概率已经掉到22%，短债先松口气。')
            out['text'] = json.dumps(v, ensure_ascii=False)
        return out


def test_soft_checks_trigger_one_structure_regen(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    fake = SpeakerFake({'why_unit_ids': ['cu-jobs'], 'so_what_unit_ids': ['cu-odds']})
    result = compose.compose_source(SOURCE, 'zh_macro', fake, post_type='judgment_take',
                                    extracted_units=[dict(u) for u in POOL], exemplars=False,
                                    emotion_contract=False, now=NOW)
    sr = result['structure_retry']
    first = {f['code'] for f in sr['first_findings']}
    assert {'speaker_first_person', 'connective_repeat'} <= first and sr['kept'] == 'retry'
    assert '我们' not in result['body'] and result['qa']['hard'] == []
    regen = [p for p in fake.payloads['compose'] if str(p.get('rewrite_note', '')).startswith('[structure_repair]')]
    assert len(regen) == 1
