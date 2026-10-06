"""Oct 6 v11 ZH fix (/workspace/x/fd_zh_rootcause_oct6.md): the "why" and "what it means" were removed
before the model wrote anything. Fakes only - no model calls."""
import json

import pytest

from live import compose, stance as stance_mod
from live.numeric_fidelity import inventory

NOW = '2026-10-06'
SRC_TEXT = 'Glassnode weekly: payrolls, Fed speakers and hike odds.'
SOURCE = {'id': 'source-glassnode', 'source_id': 'nextplatform', 'source_hash': 'g' * 64, 'original_text': SRC_TEXT,
          'author_name': 'Glassnode', 'title': 'Week on-chain', 'published_at': '2026-10-05T00:00:00Z',
          'source_language': 'en', 'source_version': 'v1'}


def _u(uid, kind, statement, numbers=(), fc='current', view=None, speaker='Glassnode'):
    unit = {'unit_id': uid, 'kind': kind, 'statement': statement, 'usage': 'paraphrase',
            'source_spans': [{'paragraph_id': 'P1', 'exact_text': statement}],
            'numbers': [{'text': n, 'metric': 'm', 'period': 'p', 'span_ref': 0,
                         'quantity': [list(q) for q in inventory(n)]} for n in numbers],
            'speaker': speaker, 'speaker_type': 'media', 'freshness_class': fc,
            'published_at': '2026-10-05T00:00:00Z'}
    if view:
        unit['view'] = view
    return unit


WILLIAMS = {'direction': 'neutral', 'subject': 'Fed rate hikes after the September hike', 'conviction': 'medium',
            'reasoning': ['no urgency to raise rates again after the September hike'], 'horizon': 'weeks'}
# v9a #1 zh_macro pool (/workspace/x/rc_oct6/rated_packs.txt): the old pack got cu-curve + cu-pce.
POOL = [
    _u('cu-view', 'view', 'New York Fed President John Williams indicated there was no urgency to raise rates '
       'again after the September hike, saying the Fed had time to gather more information before moving.',
       view=WILLIAMS),
    _u('cu-curve', 'fact', "The US yield curve was inverted from mid-2022 to late 2024 following the Fed's rapid "
       'rate hike cycle.', fc='evergreen'),
    _u('cu-pce', 'fact', "Core PCE inflation ran at 3.0% over the past year, above the Fed's 2% target.", ['3.0%', '2%']),
    _u('cu-jobs', 'fact', 'The US economy added 29,000 jobs in September, well below the 84,000 expected, and the '
       'unemployment rate rose to 4.2%.', ['29,000', '84,000', '4.2%']),
    _u('cu-avg', 'fact', 'The three-month average pace of US hiring stands at approximately 51,000 jobs per month.',
       ['51,000']),
    _u('cu-odds', 'fact', 'Fed funds futures placed the probability of an October rate hike at 22% by Friday '
       'afternoon, down from 66% on Monday.', ['22%', '66%']),
    _u('cu-jeff', 'view', 'Fed Vice Chair Philip Jefferson said the Fed may need more time and data before its next '
       'rate move.'),
    _u('cu-mech', 'mechanism', 'A weak labour market lowers the bar for the Fed to pause because wage pressure eases.',
       fc='evergreen'),
]


def _ids(units):
    return [u['unit_id'] for u in units]


# ---------------- fix 1: evidence pack by relation to the view ----------------

def test_stance_context_sees_every_usable_unit_current_first():
    ctx = compose.stance_context_units(POOL[0], POOL + [_u('cu-topic', 'fact', 'x')], now=NOW)
    ids = _ids(ctx)
    assert 'cu-view' not in ids and set(ids) == set(_ids(POOL[1:])) | {'cu-topic'}
    assert ids.index('cu-jobs') < ids.index('cu-curve')            # current before evergreen
    many = [_u(f'cu-f{i}', 'fact', f'fact {i}') for i in range(30)]
    assert len(compose.stance_context_units(POOL[0], [POOL[0]] + many, now=NOW)) == compose.STANCE_CONTEXT_CAP - 1
    topic_only = dict(POOL[2], usage='topic_only')
    assert 'cu-pce' not in _ids(compose.stance_context_units(POOL[0], [POOL[0], topic_only], now=NOW))


def test_pack_uses_valid_stance_ids():
    st = {'account_view': '美联储暂时不急着再加息', 'why_unit_ids': ['cu-jobs'], 'so_what_unit_ids': ['cu-odds']}
    pack, sel = compose.select_judgment_pack(POOL[0], POOL, st, now=NOW)
    assert _ids(pack)[:3] == ['cu-view', 'cu-jobs', 'cu-odds']
    assert 'cu-mech' in _ids(pack) and len(pack) <= compose.JUDGMENT_PACK_MAX
    assert sel['method'] == 'stance' and sel['why'] == ['cu-jobs'] and sel['so_what'] == ['cu-odds']
    assert sel['mechanism'] == 'cu-mech'


def test_pack_fallback_by_relation_never_freshness_and_never_invents():
    st = {'account_view': '美联储暂时不急着再加息',
          'view': dict(WILLIAMS, reasoning=['September payrolls added only 29,000 jobs'])}
    pack, sel = compose.select_judgment_pack(POOL[0], POOL, st, now=NOW)
    ids = _ids(pack)
    assert sel['method'] == 'fallback'
    assert sel['why'] == ['cu-jobs']                      # number + token overlap with the reasoning
    assert sel['so_what'] == ['cu-odds']                  # consequence cue: probability / futures
    assert 'cu-curve' not in ids                          # evergreen background is not the reason
    assert set(ids) <= set(_ids(POOL)) and len(ids) <= 4
    # no stance ids, no reasoning overlap: still a relation-ranked pack, still bounded
    pack2, sel2 = compose.select_judgment_pack(POOL[0], POOL, None, now=NOW)
    assert sel2['so_what'] == ['cu-odds'] and len(pack2) <= 4


def test_invalid_stance_ids_fall_back():
    st = {'account_view': 'x', 'why_unit_ids': ['cu-nope', 'cu-jeff'], 'so_what_unit_ids': ['cu-view']}
    pack, sel = compose.select_judgment_pack(POOL[0], POOL, st, now=NOW)
    assert 'cu-jeff' not in sel['why'] and sel['slots']['why'] == 'fallback'
    assert sel['so_what'] and sel['so_what'][0] != 'cu-view'


def test_validate_pack_ids_soft():
    ctx = [u for u in POOL if u['unit_id'] != 'cu-view']
    value = {'why_unit_ids': ['cu-jobs', 'cu-jeff', 'cu-mech', 'cu-pce'], 'so_what_unit_ids': ['cu-odds', 'cu-pce']}
    stance_mod.validate_pack_ids(value, ctx)
    assert value['why_unit_ids'] == ['cu-jobs', 'cu-mech']          # view dropped, max 2
    assert value['so_what_unit_ids'] == ['cu-odds']
    assert {d['id'] for d in value['pack_ids_dropped']} == {'cu-jeff', 'cu-pce'}


class JudgmentFake:
    """stance + compose fake for the v9a #1 pool."""

    def __init__(self, stance_extra=None, body=None):
        self.stance_extra = stance_extra or {}
        self.body = body or ('美联储暂时不急着再加息。\n因为9月新增就业只有2.9万，远低于预期。\n'
                             '对市场来说，10月加息的概率已经掉到22%。')
        self.payloads = {}
        self.systems = {}

    def __call__(self, stage, messages, max_tokens):
        p = json.loads(messages[-1]['content'])
        self.payloads.setdefault(stage, []).append(p)
        self.systems.setdefault(stage, []).append(messages[0]['content'])
        if stage == 'stance' and 'unit' in p:
            value = {'decision': 'take', 'account_view': '美联储暂时不急着再加息，因为9月就业太弱',
                     'supporting_unit_ids': [p['unit']['unit_id']], 'rationale': 'weak payrolls', 'confidence': .6,
                     **self.stance_extra}
        elif stage == 'stance':
            value = {'account_view': p.get('account_view')}
        else:
            ids = [u['unit_id'] for u in p['units']]
            fact = next((i for i in ids if i == 'cu-jobs'), ids[0])
            value = {'body': self.body, 'claim_ledger': [{'claim': '9月新增就业只有2.9万', 'unit_id': fact, 'span_ref': 0}]}
        return {'text': json.dumps(value, ensure_ascii=False), 'finish_reason': 'stop', 'model': 'fake'}


def _iso(monkeypatch, tmp_path):
    from live import anti_repeat
    monkeypatch.setattr(anti_repeat, 'HISTORY_DIR', tmp_path / 'h')
    monkeypatch.setattr(anti_repeat, 'FALLBACK_DIR', tmp_path / 'h')


def _compose(fake, account='zh_macro', **kw):
    return compose.compose_source(SOURCE, account, fake, post_type='judgment_take', extracted_units=[dict(u) for u in POOL],
                                  exemplars=False, emotion_contract=False, now=NOW, **kw)


def test_compose_stance_sees_all_units_and_pack_follows_stance(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    fake = JudgmentFake({'why_unit_ids': ['cu-jobs'], 'so_what_unit_ids': ['cu-odds']})
    result = _compose(fake)
    ctx = {u['unit_id'] for u in fake.payloads['stance'][0]['context_units']}
    assert ctx == set(_ids(POOL)) - {'cu-view'}                    # not the trimmed 3-unit pack
    sent = _ids(fake.payloads['compose'][0]['units'])
    assert sent[:3] == ['cu-view', 'cu-jobs', 'cu-odds'] and 'cu-curve' not in sent
    assert result['pack_selection']['method'] == 'stance'
    assert result['pack_selection']['why'] == ['cu-jobs'] and result['pack_selection']['so_what'] == ['cu-odds']
    # number caps still come from the shape / evidence budget (more units != more numbers)
    assert fake.payloads['compose'][0]['evidence_budget']['max_numbers'] <= compose.EVIDENCE_BUDGET['max_numbers']


def test_compose_pack_fallback_recorded(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    fake = JudgmentFake()
    result = _compose(fake)
    assert result['pack_selection']['method'] == 'fallback'
    assert result['pack_selection']['so_what'] == ['cu-odds']
    assert len(result['units']) <= compose.JUDGMENT_PACK_MAX


# ---------------- fix 2: ZH judgment line keeps its reason; why_line / so_what_line ----------------

from live import registry, zh_register as zr   # noqa: E402


def test_stance_rule_allows_reason_and_50_chars():
    assert zr.STANCE_MAX_CJK == 50 and '50' in zr.STANCE_RULE_ZH
    assert '意味着' not in zr.STANCE_RULE_ZH and '取决于' not in zr.STANCE_RULE_ZH
    assert '别…' in zr.STANCE_RULE_ZH and '结构性' in zr.STANCE_RULE_ZH      # 别… + research-word bans stay
    call = '美联储10月大概率不会再加息了，因为9月新增就业只有2.9万，比市场预期的8.4万差了一大截，就业撑不住'
    assert 35 < len(zr.CJK.findall(call)) <= 50 and zr.stance_view_findings(call) == []
    assert zr.stance_view_findings('别指望美联储10月再加息')


def test_rewrite_rejects_dropping_the_reason():
    def fake(stage, messages, max_tokens):
        return {'text': json.dumps({'account_view': '美联储10月不会加息'}, ensure_ascii=False),
                'finish_reason': 'stop', 'model': 'f'}
    original = '美联储10月不会再加息，因为9月非农只有2.9万，这种结构性走弱的就业数据让加息的理由越来越站不住了'
    value = {'account_view': original, 'view': {}}
    meta = stance_mod.zh_account_view_rewrite(fake, value, [])
    assert meta['kept'] == 'original' and meta['reject_reason'] == 'dropped_reason'
    assert value['account_view'] == original


def test_support_lines_validated_softly():
    units = [POOL[3], POOL[5]]
    value = {'why_line': '9月新增就业只有2.9万，远低于预期', 'so_what_line': '10月加息的概率已经掉到22%'}
    stance_mod.validate_support_lines(value, units)
    assert value['why_line'] and value['so_what_line'] and 'support_lines_dropped' not in value
    value = {'why_line': '纽约联储主席Williams明确表态没有紧迫性', 'so_what_line': '加息概率掉到15%'}
    stance_mod.validate_support_lines(value, units)
    assert 'why_line' not in value and 'so_what_line' not in value
    assert {d['reason'] for d in value['support_lines_dropped']} == {'said_only', 'new_numbers'}


def test_numbers_covered_scale_conversions():
    assert zr.numbers_covered('9月新增就业只有2.9万', ['The US economy added 29,000 jobs in September'])
    assert zr.numbers_covered('542.3亿美元', ['$54.23 billion']) and zr.numbers_covered('二季度', ['Q2'])
    assert not zr.numbers_covered('概率33%', ['odds 22%'])


def test_judgment_line_may_be_50_chars_rest_follows_donor_median():
    line1 = '美联储10月大概率不会再加息了，因为9月新增就业只有2.9万，比市场预期的8.4万差了一大截。'
    assert zr.sentence_findings(line1 + '\n对债市来说，短端压力小了。\n接下来看10月通胀。') == []
    too_long = '美联储10月大概率不会再加息了，因为9月新增就业只有2.9万，远远低于此前市场普遍预期的8.4万，失业率还一路升到了4.2%，就业明显撑不住了。'
    assert '第一句判断' in zr.sentence_findings(too_long + '\n短端压力小了。')[0]['detail']
    rest = '后面这一句写得特别特别长而且一直不断句一口气把好几件事情全都塞进来了看着就累。'
    assert zr.sentence_findings(line1 + '\n' + rest + '\n' + rest)[0]['code'] == 'zh_sentence_length'


def test_zh_compose_payload_carries_why_and_so_what(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    fake = JudgmentFake({'why_unit_ids': ['cu-jobs'], 'so_what_unit_ids': ['cu-odds'],
                         'why_line': '9月新增就业只有2.9万，远低于预期的8.4万',
                         'so_what_line': '10月加息的概率从66%掉到了22%'})
    result = _compose(fake)
    p = fake.payloads['compose'][0]
    assert p['why_line'].startswith('9月新增就业') and p['so_what_line'].startswith('10月加息')
    assert p['pack_roles'] == {'why': ['cu-jobs'], 'so_what': ['cu-odds'], 'mechanism': 'cu-mech'}
    system = fake.systems['compose'][0]
    assert 'why_line' in system and 'so_what_line' in system and '50 个字' in system
    assert result['stance']['why_line'] == p['why_line']


def test_en_compose_instructions_unchanged(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    fake = JudgmentFake({'why_unit_ids': ['cu-jobs'], 'so_what_unit_ids': ['cu-odds'],
                         'why_line': 'Payrolls rose only 29,000 against 84,000 expected.',
                         'so_what_line': 'October hike odds fell to 22%.'},
                        body='The Fed is in no hurry to hike again.\nPayrolls rose only 29,000.\nOdds fell to 22%.')
    fake_view = 'The Fed is in no hurry to hike again because payrolls missed'
    orig = fake.__call__

    def en_call(stage, messages, max_tokens):
        out = orig(stage, messages, max_tokens)
        if stage == 'stance':
            v = json.loads(out['text']); v['account_view'] = fake_view; out['text'] = json.dumps(v)
        return out
    compose.compose_source(SOURCE, 'en_macro', en_call, post_type='judgment_take', extracted_units=[dict(u) for u in POOL],
                           exemplars=False, emotion_contract=False, now=NOW)
    p = fake.payloads['compose'][0]
    assert 'why_line' not in p and 'pack_roles' not in p and 'zh_register' not in p
    assert p['stance']['why_line'].startswith('Payrolls')          # optional support inside the stance only
    assert fake.systems['compose'][0] == compose.COMPOSE


# ---------------- fix 3: ZH emotion low, no irony / exaggeration, intensifier density ----------------

from live import emotion_contract as ec, qa_levels   # noqa: E402


@pytest.mark.parametrize('account', ['zh_macro', 'zh_industry'])
def test_zh_personas_low_tier_target_two(account):
    assert ec.persona_tier(account) == 'low'
    brief = ec.build_emotion_brief([POOL[3]], {'account_view': '美联储暂时不急着加息'}, lang='zh', account_id=account)
    assert brief['target_intensity'] == 2
    assert not {'light exaggeration', 'irony', 'rhetorical question'} & set(brief['allowed_devices'])
    assert brief['zh_rule'] == ec.ZH_EMOTION_RULE and '反讽' in brief['zh_rule']
    assert 'irony or a rhetorical jab' not in brief['required_effect']


def test_zh_high_tier_brief_never_invites_irony_and_en_unchanged():
    zh = ec.build_emotion_brief([POOL[3]], {'account_view': 'x'}, lang='zh', account_id='crypto_macro_zh')
    assert 'irony or a rhetorical jab' not in zh['required_effect'] and 'irony' not in zh['allowed_devices']
    en = ec.build_emotion_brief([POOL[3]], {'account_view': 'x'}, lang='en', account_id='crypto_macro_en')
    assert 'irony' in en['allowed_devices'] and 'light exaggeration' in en['allowed_devices']
    assert 'zh_rule' not in en


def test_system_zh_says_emotion_via_judgment_verbs():
    assert '情绪靠判断动词带出来' in zr.SYSTEM_ZH and '反讽' in zr.SYSTEM_ZH


def test_intensifier_density_finding():
    v9a = ('此次加息后美联储其实一点都不急着继续动手，接下来纯粹是走过场看数据\n'
           '纽约联储主席Williams直接放话毫无紧迫性，哪怕核心PCE还在3.0%的高位挂着\n'
           '官方对通胀指标的无视，说明市场短期内继续收紧的预期已经打没了。')
    f = zr.intensifier_findings(v9a)
    assert f and f[0]['code'] == 'zh_intensifier' and '走过场' in f[0]['detail']
    dense = '数据很差。降息根本没戏，完全看不到。直接停手。'
    assert zr.intensifier_findings(dense)
    plain = '美联储暂时不急着再加息。\n因为9月新增就业只有2.9万，远低于预期。\n对市场来说，10月加息的概率已经掉到22%。'
    assert zr.intensifier_findings(plain) == []
    one = plain + '\n这次就业数据直接改变了节奏，之后几周看通胀和工资，短端利率的压力也会小一些。'
    assert zr.intensifier_findings(one) == []        # a single 直接 in a normal post is not a finding
    assert zr.intensifier_findings(v9a, 'en') == []
    assert qa_levels.level({'code': 'zh_intensifier'}, frame_found=False) == 'soft'
    assert 'zh_intensifier' in qa_levels.FIXES


def test_intensifier_joins_single_structure_regen(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    from tests.test_compose import SOURCE as CSOURCE
    from tests.test_zh_register_oct6_v5 import SeqFake, STANCE
    loud = '存储这轮紧缺还没完。\n因为厂商一点都不想扩产，价格纯粹是被推上去的，直接涨。\n对下游来说，采购节奏得跟着改。'
    calm = '存储这轮紧缺还没完。\n因为厂商就是不想扩产，价格其实还在涨。\n对下游来说，采购节奏得跟着改。'
    fake = SeqFake([loud, calm])
    result = compose.compose_source(CSOURCE, 'zh_industry', fake, post_type='data_take',
                                    stance_output=dict(STANCE), emotion_contract=False)
    sr = result['structure_retry']
    assert 'zh_intensifier' in {f['code'] for f in sr['first_findings']} and sr['kept'] == 'retry'
    assert len([p for p in fake.payloads if str(p.get('rewrite_note', '')).startswith('[structure_repair]')]) == 1


# ---------------- fix 4: prompt conflicts (意味着 allowed, no 说白了 / literal lead-ins) ----------------

from live import compose_shapes as cs   # noqa: E402

LITERAL_LEADINS = ('背后是', '靠的是', '对…来说', '接下来要看', '有什么影响')


def _prompt_texts():
    texts = {'SYSTEM_ZH': zr.SYSTEM_ZH, 'RULES_ZH': ' '.join(zr.RULES_ZH),
             'FIXES.missing_why': qa_levels.FIXES['missing_why'],
             'FIXES.missing_implication': qa_levels.FIXES['missing_implication']}
    texts.update({f'shape.{sid}': spec['zh'] for sid, spec in cs.SHAPES.items()})
    return texts


def test_plain_causal_and_implication_connectors_allowed():
    assert not zr.FORMAL_RX.search('这意味着10月加息基本没戏了')
    assert zr.register_findings('美联储暂时不加息。\n因为就业太弱。\n这意味着短端利率的压力会小一些，所以债市先松口气。') == []
    for word in ('从而', '进而', '鉴于'):
        assert zr.FORMAL_RX.search(word)                          # research words stay
    rule4 = next(line for line in zr.SYSTEM_ZH.splitlines() if line.startswith('4.'))
    assert '意味着' not in rule4.split('平实')[0] and '这意味着' in rule4 and '从而' in rule4


def test_shuobaile_never_recommended_but_still_banned():
    for name, text in _prompt_texts().items():
        assert '说白了' not in text, name
    assert not zr.IMPLICATION_RX.search('说白了，下游等不到降价。')
    assert '说白了' in compose.COMPOSE                                       # banned in COMPOSE
    assert any('说白了' in show for show, _ in compose.template_patterns('zh'))   # and in avoid_patterns
    persona = registry.persona_for_account('zh_macro')
    assert '说白了' not in zr.connectors(persona)


def test_no_literal_leadins_as_templates_function_described():
    for name, text in _prompt_texts().items():
        for word in LITERAL_LEADINS:
            assert word not in text, (name, word)
    assert '一句说清原因' in zr.SYSTEM_ZH and '一句说清影响' in zr.SYSTEM_ZH
    assert '谁受益谁吃亏' in zr.SYSTEM_ZH and '还没被定价' in zr.SYSTEM_ZH


def test_not_x_but_y_forms_stay_banned_in_prompt_and_checks():
    for form in ('不是X，而是Y', '不是X，是Y'):
        assert form in compose.COMPOSE
    assert '「不是X，而是Y」及其问句版' in zr.SYSTEM_ZH
    assert zr.register_findings('这次不是需求问题，而是供给问题。')
    assert zr.register_findings('Zendesk这次换CFO只是常规的财务招聘？人家这是把财务治理绑在AI产品战略上。')
    shows = [show for show, rx in compose.template_patterns('zh') if rx.search('降息不是救市，是补课。')]
    assert '不是X，是Y' in shows
    assert '「不是X而是Y」句式' in zr.stance_view_findings('这次CFO任命不是常规招聘，而是AI战略布局')


def test_leadin_repeat_soft_cross_draft():
    prev = ['美联储不急。\n背后是就业太弱。\n对市场来说，短端松了。', '油价撑不久。\n背后是需求没跟上。\n所以减产要盯。']
    body = '存储还会紧。\n背后是厂商不扩产。\n下游得早点补货。'
    f = zr.leadin_repeat_findings(body, prev)
    assert f and f[0]['code'] == 'structure_repeat' and '背后是' in f[0]['detail']
    assert zr.leadin_repeat_findings(body, ['油价撑不久。\n需求没跟上。', '美联储不急。\n因为就业太弱。']) == []
    assert zr.leadins('对债市来说，短端松了。接下来得看通胀。') == ['对…来说', '接下来要看']
    assert zr.leadins('因为就业太弱。所以先停。') == []                         # plain connectors are fine
    rows = [{'text': t} for t in prev]
    assert any('背后是' in x['detail'] for x in cs.history_findings(body, rows))   # post-level soft check too
    assert qa_levels.level({'code': 'structure_repeat'}, frame_found=False) == 'soft'
