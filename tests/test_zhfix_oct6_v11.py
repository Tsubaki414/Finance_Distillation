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


def test_crypto_zh_keeps_high_emotion_irony_and_required_effect():
    # v11 follow-up (Fiona): only restrained personas lose irony / exaggeration; crypto keeps its voice.
    zh = ec.build_emotion_brief([POOL[3]], {'account_view': 'x'}, lang='zh', account_id='crypto_macro_zh')
    assert zh['tier'] == 'high' and zh['target_intensity'] >= 4
    assert {'irony', 'light exaggeration'} <= set(zh['allowed_devices'])
    assert 'rhetorical question' not in zh['allowed_devices']            # v9 ZH-wide rule unchanged
    assert zh['required_effect'] == ec.REQUIRED_EFFECT['high'] and 'zh_rule' not in zh
    en = ec.build_emotion_brief([POOL[3]], {'account_view': 'x'}, lang='en', account_id='crypto_macro_en')
    assert {'irony', 'light exaggeration'} <= set(en['allowed_devices']) and en['target_intensity'] >= 4
    assert en['required_effect'] == ec.REQUIRED_EFFECT['high'] and 'zh_rule' not in en


def test_restrained_persona_list_is_data_driven(monkeypatch, tmp_path):
    cfg = json.loads(ec.TIERS_PATH.read_text())
    assert cfg['restrained_devices_personas'] == ['zh_macro', 'zh_industry']
    assert cfg['why_cites_fact_en_personas'] == ['crypto_macro_en']
    assert not ec.restrained_devices('crypto_macro_zh') and ec.restrained_devices('zh_macro')
    # the list, not the language, decides: drop zh_industry from it and its brief gets irony back
    cfg['restrained_devices_personas'] = ['zh_macro']
    path = tmp_path / 'emotion_tiers.json'
    path.write_text(json.dumps(cfg))
    monkeypatch.setattr(ec, 'TIERS_PATH', path)
    brief = ec.build_emotion_brief([POOL[3]], {'account_view': 'x'}, lang='zh', account_id='zh_industry')
    assert 'irony' in brief['allowed_devices'] and 'zh_rule' not in brief


def test_system_zh_restraint_rides_on_the_brief():
    assert '情绪靠判断动词带出来' in ec.ZH_EMOTION_RULE and '反讽' in ec.ZH_EMOTION_RULE
    assert 'zh_rule' in zr.SYSTEM_ZH and '不能顶替理由' in zr.SYSTEM_ZH
    # SYSTEM_ZH no longer forbids irony / intensifiers outright (crypto personas keep them)
    assert '不靠夸张、反讽或强化词；' not in zr.SYSTEM_ZH and '别拿近义的强化词顶上' not in zr.SYSTEM_ZH


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
    assert zr.intensifier_findings(v9a, restrained=False) == []      # crypto / HIGH personas: never flagged
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
    # zh_native: no connective is required; 这意味着 / 其实 at most once per post (was: 这意味着 recommended)
    assert '这意味着' in rule4 and '最多出现一次' in rule4 and '不要求用' in rule4 and '从而' in rule4


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
    assert '谁受益谁吃亏' in zr.SYSTEM_ZH and '接下来该盯什么' in zr.SYSTEM_ZH   # Oct 7: no 还没被定价 ask


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


# ---------------- fix 5: fewer short shapes for research-type ZH sources ----------------

LONG_NOTE_TEXT = 'Payrolls missed badly. ' * 80


def _shape_units():
    return [dict(u) for u in POOL]


def test_research_source_signal():
    assert cs.research_source({'original_text': LONG_NOTE_TEXT}, [])[0]
    assert cs.research_source({'original_text': 'short'}, _shape_units())[1]['reason'] == 'many_units'
    flash = {'adapter': 'flash:ch141_wscn_flash', 'source_version': 'flash-v1', 'original_text': LONG_NOTE_TEXT}
    assert cs.research_source(flash, _shape_units()) == (False, {'reason': 'flash', 'adapter': 'flash:ch141_wscn_flash'})
    assert not cs.research_source({'original_text': '美联储加息25个基点。'}, _shape_units()[:2])[0]


@pytest.mark.parametrize('seed', [f's{i}' for i in range(12)])
def test_zh_research_source_never_take_short_and_short_capped(seed):
    persona = registry.persona_for_account('zh_macro')
    units = _shape_units()
    out = cs.choose_shape(persona, units=units, all_units=units, seed=seed, source={'original_text': LONG_NOTE_TEXT})
    assert out['id'] != 'take_short' and 'take_short' not in out['candidates']
    assert out['research_source'] is True
    base = cs.persona_shapes(persona)
    for sid, spec in cs.SHAPES.items():
        if spec['length'] == 'short' and sid in out['candidates'] and sid in base:
            assert base[sid] > cs.ZH_RESEARCH_SHORT_WEIGHT            # zh_macro short 0.685 really capped
    if out['id'] == 'one_number_punch':
        assert out['max_numbers'] == 2


def test_zh_flash_and_en_keep_old_shapes():
    persona = registry.persona_for_account('zh_macro')
    units = _shape_units()
    flash = {'adapter': 'flash:ch141_wscn_flash', 'original_text': LONG_NOTE_TEXT}
    seen = {cs.choose_shape(persona, units=units, all_units=units, seed=f's{i}', source=flash)['id'] for i in range(40)}
    assert 'take_short' in seen                                       # flashes keep the donor short mix
    en = registry.persona_for_account('en_macro')
    out = cs.choose_shape(en, units=units, all_units=units, seed='s1', source={'original_text': LONG_NOTE_TEXT})
    assert 'research_source' not in out


def test_research_punch_payload_allows_second_number_for_the_why():
    shape = {'id': 'one_number_punch', 'research_source': True, **cs.ZH_RESEARCH_PUNCH}
    block = cs.payload_block(shape, 'zh', {'min': 60, 'max': 300})
    assert block['max_numbers'] == 2 and block['max_number_lines'] == 2
    assert '第二个数字' in block['structure'] and '为什么' in block['structure']
    assert compose.number_budget(block) == 2
    plain = cs.payload_block({'id': 'one_number_punch'}, 'zh', {'min': 60, 'max': 300})
    assert plain['max_numbers'] == 1 and '第二个数字' not in plain['structure']


def test_rotation_still_avoids_last_shape_on_research_source():
    persona = registry.persona_for_account('zh_macro')
    units = _shape_units()
    src = {'original_text': LONG_NOTE_TEXT}
    first = cs.choose_shape(persona, units=units, all_units=units, seed='r1', source=src)
    second = cs.choose_shape(persona, units=units, all_units=units, seed='r1', source=src,
                             recent=[{'shape': first['id'], 'text': 'x'}])
    assert second['id'] != first['id'] and second['last_shape'] == first['id']


def test_compose_records_research_shape(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    fake = JudgmentFake({'why_unit_ids': ['cu-jobs'], 'so_what_unit_ids': ['cu-odds']})
    result = _compose(fake)
    shape = result['composition_shape']
    assert shape['research_source'] is True and shape['id'] != 'take_short'


# ---------------- fix 6: translate units to Chinese first (stance zh_units), then compose ----------------

ZH_UNITS = {'cu-view': '纽约联储主席John Williams表示，9月加息后没有再次加息的紧迫性，美联储有时间收集更多信息再行动。',
            'cu-jobs': '美国9月新增就业2.9万个，远低于道琼斯调查预期的8.4万个，失业率升至4.2%。',
            'cu-odds': '截至周五下午，联邦基金期货显示10月加息概率为22%，周一时为66%。'}


def test_validate_zh_units_keeps_numbers_or_falls_back():
    value = {'zh_units': dict(ZH_UNITS, **{'cu-pce': '核心PCE通胀高于美联储目标。',     # lost 3.0% / 2%
                                           'cu-nope': '不存在的单元翻译文本。', 'cu-avg': 'average pace 51,000'})}
    stance_mod.validate_zh_units(value, POOL)
    assert set(value['zh_units']) == set(ZH_UNITS)
    reasons = {r['unit_id']: r['reason'] for r in value['zh_units_rejected']}
    assert reasons == {'cu-pce': 'numbers_lost', 'cu-nope': 'unknown_unit', 'cu-avg': 'not_chinese'}


def test_zh_stance_requests_translation_en_does_not(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    fake = JudgmentFake({'why_unit_ids': ['cu-jobs'], 'so_what_unit_ids': ['cu-odds'], 'zh_units': ZH_UNITS})
    result = _compose(fake)
    assert fake.payloads['stance'][0]['zh_units_rule'] == stance_mod.ZH_UNITS_RULE
    units = {u['unit_id']: u for u in fake.payloads['compose'][0]['units']}
    assert units['cu-jobs']['statement'] == ZH_UNITS['cu-jobs']
    assert units['cu-jobs']['statement_en'].startswith('The US economy added 29,000 jobs')
    assert units['cu-jobs']['source_spans'] == [POOL[3]['statement']]                # spans / numbers unchanged
    assert [n['text'] for n in units['cu-jobs']['numbers']] == ['29,000', '84,000', '4.2%']
    assert 'statement_en' not in units['cu-mech']                                  # untranslated unit stays English
    assert 'zh_units' not in fake.payloads['compose'][0]['stance']
    assert 'statement_en' in fake.systems['compose'][0] and '不是让你润色' in fake.systems['compose'][0]   # zh_native
    # post checks still run on the English source units
    assert {u['unit_id']: u['statement'] for u in result['units']}['cu-jobs'] == POOL[3]['statement']


def test_zh_unit_translation_env_off(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    monkeypatch.setenv('FD_ZH_UNIT_TRANSLATE', '0')
    fake = JudgmentFake({'zh_units': ZH_UNITS})
    _compose(fake)
    assert 'zh_units_rule' not in fake.payloads['stance'][0]
    assert not any('statement_en' in u for u in fake.payloads['compose'][0]['units'])


def test_en_stance_never_asks_for_translation():
    assert not stance_mod.zh_units_enabled({'lang': 'en'}) and stance_mod.zh_units_enabled({'lang': 'zh'})


# ---------------- fix 7: missing_why checks that the reason cites a fact ----------------

HEAD_BODY = ('美联储短期内不会再加息了。\n背后是哪怕核心PCE通胀还在3.0%，纽约联储主席Williams也明确表态没有紧迫性。\n'
             '对市场来说，押注连续收紧的交易可以歇了。')
REAL_BODY = ('美联储短期内不会再加息了。\n因为9月新增就业只有2.9万，远低于预期的8.4万。\n'
             '对市场来说，10月加息的概率已经从66%掉到22%。')


def _why(body, **kw):
    return [f for f in zr.why_implication_findings(body, 'zh', **kw) if f['code'] == 'missing_why']


def test_said_reason_with_keyword_does_not_pass():
    ledger = [{'claim': 'Williams明确表态没有紧迫性', 'unit_id': 'cu-view', 'span_ref': 0}]
    f = _why(HEAD_BODY, units=POOL, ledger=ledger)
    assert f and f[0]['detail'] == '理由只是某人表态，没有事实'
    assert _why(HEAD_BODY)                                       # keyword-only (背后是 + 表态) fails without units too


def test_fact_backed_reason_passes():
    assert _why(REAL_BODY, units=POOL, ledger=[]) == []          # 2.9万 / 8.4万 from the payroll fact unit
    body = '美联储短期内不会再加息了。\n背后是就业数据一下子变得很难看。\n对市场来说，短端利率压力小了。'
    ledger = [{'claim': '就业数据一下子变得很难看', 'unit_id': 'cu-jobs', 'span_ref': 0}]
    assert _why(body, units=POOL, ledger=ledger) == []           # ledger row on a fact unit


def test_reason_mapped_to_view_unit_is_missing_why():
    body = '美联储短期内不会再加息了。\n背后是官方觉得手上时间还多。\n对市场来说，短端利率压力小了。'
    ledger = [{'claim': '官方觉得手上时间还多', 'unit_id': 'cu-view', 'span_ref': 0}]
    f = _why(body, units=POOL, ledger=ledger)
    assert f and '观点单元' in f[0]['detail']


def test_zh_unit_translation_lets_a_paraphrase_count():
    body = '美联储短期内不会再加息了。\n因为新增就业远低于道琼斯调查的预期。\n对市场来说，短端利率压力小了。'
    assert stance_mod and zr.reason_support('因为新增就业远低于道琼斯调查的预期', POOL, [],
                                            {'cu-jobs': ZH_UNITS['cu-jobs']})[0] == 'fact'
    assert _why(body, units=POOL, ledger=[], zh_units={'cu-jobs': ZH_UNITS['cu-jobs']}) == []


def test_missing_why_soft_single_regen_and_yellow_flag(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)

    class Fake(JudgmentFake):
        def __call__(self, stage, messages, max_tokens):
            out = super().__call__(stage, messages, max_tokens)
            if stage == 'compose':
                n = len(self.payloads['compose'])
                v = json.loads(out['text'])
                v['body'] = HEAD_BODY if n == 1 else REAL_BODY
                v['claim_ledger'] = ([{'claim': 'Williams也明确表态没有紧迫性', 'unit_id': 'cu-view', 'span_ref': 0}]
                                     if n == 1 else [{'claim': '9月新增就业只有2.9万', 'unit_id': 'cu-jobs', 'span_ref': 0}])
                out['text'] = json.dumps(v, ensure_ascii=False)
            return out
    fake = Fake({'why_unit_ids': ['cu-jobs'], 'so_what_unit_ids': ['cu-odds']})
    result = _compose(fake)
    sr = result['structure_retry']
    first = [f for f in sr['first_findings'] if f['code'] == 'missing_why']
    assert first and first[0]['detail'] == '理由只是某人表态，没有事实'
    assert sr['kept'] == 'retry' and result['body'] == REAL_BODY
    assert not [f for f in result['post_checks'] if f['code'] == 'missing_why']
    assert len([p for p in fake.payloads['compose'] if str(p.get('rewrite_note', '')).startswith('[structure_repair]')]) == 1


def test_missing_why_never_blocks(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)

    class Stubborn(JudgmentFake):
        def __call__(self, stage, messages, max_tokens):
            out = super().__call__(stage, messages, max_tokens)
            if stage == 'compose':
                v = json.loads(out['text'])
                v['body'] = HEAD_BODY
                v['claim_ledger'] = [{'claim': 'Williams也明确表态没有紧迫性', 'unit_id': 'cu-view', 'span_ref': 0}]
                out['text'] = json.dumps(v, ensure_ascii=False)
            return out
    result = _compose(Stubborn())
    flags = [f for f in result['post_checks'] if f['code'] == 'missing_why']
    assert flags and all(f['level'] == 'soft' for f in flags)
    assert 'missing_why' not in result['qa']['hard'] and 'missing_why' in result['qa']['soft']
    assert result['structure_retry']['kept'] == 'original'


# ---------------- v11 follow-up: crypto keeps emotion; why-cites-fact applies to crypto too ----------------

LOUD_ZH = '存储这轮紧缺还没完。\n因为厂商一点都不想扩产，价格纯粹是被推上去的，直接涨。\n对下游来说，采购节奏得跟着改。'


@pytest.mark.parametrize('account,flagged', [('zh_industry', True), ('crypto_macro_zh', False)])
def test_intensifier_only_for_restrained_personas(monkeypatch, tmp_path, account, flagged):
    _iso(monkeypatch, tmp_path)
    from tests.test_compose import SOURCE as CSOURCE
    from tests.test_zh_register_oct6_v5 import SeqFake, STANCE
    result = compose.compose_source(CSOURCE, account, SeqFake([LOUD_ZH, LOUD_ZH]), post_type='data_take',
                                    stance_output=dict(STANCE), emotion_contract=False)
    first = {f['code'] for f in (result.get('structure_retry') or {}).get('first_findings') or []}
    posts = {f['code'] for f in result['post_checks']}
    assert ('zh_intensifier' in first) is flagged and ('zh_intensifier' in posts) is flagged


def test_crypto_zh_runs_the_zh_why_check(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)

    class Said(JudgmentFake):
        def __call__(self, stage, messages, max_tokens):
            out = super().__call__(stage, messages, max_tokens)
            if stage == 'compose':
                v = json.loads(out['text'])
                v['body'] = HEAD_BODY
                v['claim_ledger'] = [{'claim': 'Williams也明确表态没有紧迫性', 'unit_id': 'cu-view', 'span_ref': 0}]
                out['text'] = json.dumps(v, ensure_ascii=False)
            return out
    result = _compose(Said(), account='crypto_macro_zh')
    flags = [f for f in result['post_checks'] if f['code'] == 'missing_why']
    assert flags and flags[0]['detail'] == '理由只是某人表态，没有事实' and flags[0]['level'] == 'soft'


EN_SAID = ('Bitcoin is not getting a Fed tailwind this month.\n'
           'That is because New York Fed President Williams said there is no urgency to hike again.\n'
           'Risk appetite stays thin into October.')
EN_FACT = ('Bitcoin is not getting a Fed tailwind this month.\n'
           'That is because payrolls rose only 29,000 against 84,000 expected.\n'
           'October hike odds fell to 22% from 66%.')


def test_en_why_said_only_reason_is_missing_why():
    ledger = [{'claim': 'Williams said there is no urgency to hike again', 'unit_id': 'cu-view', 'span_ref': 0}]
    f = zr.en_why_findings(EN_SAID, units=POOL, ledger=ledger)
    assert f and f[0]['code'] == 'missing_why' and "'X said'" in f[0]['detail']
    for marker in ('told reporters', 'argued', 'warned', 'thinks'):
        body = f'BTC looks heavy here.\nThat is driven by the Fed, which {marker} the job is not done.'
        assert zr.en_why_findings(body, units=POOL), marker
    assert zr.en_why_findings(EN_FACT, units=POOL, ledger=[]) == []      # 29,000 / 84,000 from the payroll unit
    ledger_fact = [{'claim': 'hiring slowed sharply last month', 'unit_id': 'cu-jobs', 'span_ref': 0}]
    assert zr.en_why_findings('BTC looks heavy.\nThat is due to hiring that slowed sharply last month.',
                              units=POOL, ledger=ledger_fact) == []
    assert zr.en_why_findings('BTC looks heavy. Such as gold, since 2020 it has been range-bound.', units=POOL) == []


class EnFake(JudgmentFake):
    def __init__(self, bodies, **kw):
        super().__init__(kw)
        self.bodies = list(bodies)

    def __call__(self, stage, messages, max_tokens):
        out = super().__call__(stage, messages, max_tokens)
        v = json.loads(out['text'])
        if stage == 'stance' and 'account_view' in v:
            v['account_view'] = 'Bitcoin gets no Fed tailwind this month because payrolls missed'
        if stage == 'compose':
            n = len(self.payloads['compose'])
            body = self.bodies[min(n, len(self.bodies)) - 1]
            v['body'] = body
            v['claim_ledger'] = ([{'claim': 'Williams said there is no urgency', 'unit_id': 'cu-view', 'span_ref': 0}]
                                 if body == EN_SAID else
                                 [{'claim': 'payrolls rose only 29,000', 'unit_id': 'cu-jobs', 'span_ref': 0}])
        out['text'] = json.dumps(v, ensure_ascii=False)
        return out


def _compose_en(fake, account):
    return compose.compose_source(SOURCE, account, fake, post_type='judgment_take',
                                  extracted_units=[dict(u) for u in POOL], exemplars=False, emotion_contract=False,
                                  now=NOW)


def test_crypto_en_said_reason_soft_finding_and_single_regen(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    fake = EnFake([EN_SAID, EN_FACT])
    result = _compose_en(fake, 'crypto_macro_en')
    sr = result['structure_retry']
    assert 'missing_why' in {f['code'] for f in sr['first_findings']} and sr['kept'] == 'retry'
    assert result['body'] == EN_FACT and not [f for f in result['post_checks'] if f['code'] == 'missing_why']
    assert len([p for p in fake.payloads['compose'] if str(p.get('rewrite_note', '')).startswith('[structure_repair]')]) == 1
    # stubborn model: soft yellow flag on the kept body, never a block
    _iso(monkeypatch, tmp_path / 'b')
    result = _compose_en(EnFake([EN_SAID]), 'crypto_macro_en')
    flags = [f for f in result['post_checks'] if f['code'] == 'missing_why']
    assert flags and all(f['level'] == 'soft' for f in flags) and 'missing_why' not in result['qa']['hard']


def test_en_macro_control_group_has_no_why_check(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    result = _compose_en(EnFake([EN_SAID]), 'en_macro')
    assert not [f for f in result['post_checks'] if f['code'] == 'missing_why']
    assert 'missing_why' not in {f['code'] for f in (result.get('structure_retry') or {}).get('first_findings') or []}
