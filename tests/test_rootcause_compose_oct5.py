"""Oct 5 root-cause fixes (not phrase bans): judgment-first signature openings,
thin thesis-locked packs (1 view + <=2 facts), thesis_lock / evidence_budget in the
COMPOSE payload, and a soft info_dump finding for judgment posts."""
import json
from pathlib import Path

from live import compose, qa_levels, registry

CARDS = Path(compose.__file__).with_name('personas') / 'signature_cards'
ACCOUNTS = ['zh_macro', 'zh_industry', 'en_industry', 'en_macro', 'crypto_macro_en', 'crypto_macro_zh',
            'single_stock_deepdive_en', 'trading_shortterm', 'market_data_charts', 'investing_philosophy']
DATA_PERSONAS = ('market_data_charts', 'trading_shortterm')
BANNED_OPENING_TEACHING = ('先交代来源', '真正的核心', '今晚有', '数据要公布', '就是事实', '新闻复述开头',
                           'sourced data point', 'data-calendar', 'data calendar', 'hard number on the tape right now (',
                           '一句话标题式陈述事实')


def _card(pid):
    return json.loads((CARDS / f'{pid}.json').read_text())


# --- A. signature openings -------------------------------------------------------------

def test_recipe_counts_are_thin():
    assert compose.RECIPES['judgment_take'] == ('view', 1, ('fact',), 1)
    assert compose.RECIPES['contrarian_take'] == ('view', 1, ('fact',), 1)
    assert compose.RECIPES['view_relay'] == ('view', 1, ('fact', 'mechanism'), 1)
    assert compose.RECIPES['earnings_take'] == ('fact', 2, ('view', 'mechanism'), 1)
    assert compose.RECIPES['data_take'] == ('fact', 3, ('mechanism',), 1)
    assert compose.RECIPES['mechanism_explainer'] == ('mechanism', 1, ('fact',), 2)


def test_zh_industry_and_zh_macro_openings_drop_banned_teaching():
    for pid in ('zh_industry', 'zh_macro'):
        for line in _card(pid)['openings']:
            assert not any(b in line for b in BANNED_OPENING_TEACHING), (pid, line)
    assert not any('真正的核心' in e['text'] for e in _card('zh_macro')['exemplars'])
    assert not any('真正的核心' in e['text'] or '我的判断' in e['text'] for e in _card('zh_macro')['zh_restraint'])
    assert '我的判断：' not in _card('zh_macro')['lexicon']
    assert '我的判断' not in _card('zh_macro')['donor_first_person'].replace('「我的判断：」 label', '')


def test_only_data_personas_keep_one_labelled_data_led_open():
    for pid in ACCOUNTS:
        openings = _card(pid)['openings']
        labelled = [o for o in openings if o.startswith('[data_take only]')]
        if pid in DATA_PERSONAS:
            assert len(labelled) == 1, pid
        else:
            assert not labelled, pid
        for o in openings:
            if not o.startswith('[data_take only]'):
                assert not any(b in o for b in BANNED_OPENING_TEACHING), (pid, o)


def test_industry_cards_have_hard_constraints():
    for pid in ('zh_industry', 'en_industry'):
        hard = _card(pid).get('hard_constraints')
        assert isinstance(hard, list) and 4 <= len(hard) <= 6, pid
        joined = ' '.join(hard)
        assert '2' in joined   # <= 2 numbers
        assert '我的判断' in joined or 'My read' in joined


def test_first_person_markers_do_not_teach_judgment_label():
    allowed = compose.COMPOSE.split('First person: opinion markers only', 1)[1].split(')', 1)[0]
    assert '我的判断' not in allowed and '我的看法' not in allowed


# --- B. trim + payload -----------------------------------------------------------------

def _u(i, kind, **kw):
    base = {'unit_id': f'cu-{i}', 'kind': kind, 'usage': 'cite', 'statement': f'{kind} {i}',
            'source_spans': [{'exact_text': f'span {i}'}], 'numbers': [], 'speaker': 'S',
            'speaker_type': 'media', 'freshness_class': 'current', 'published_at': '2026-10-05T00:00:00Z'}
    base.update(kw)
    return base


def test_trim_judgment_pack_keeps_one_anchor_and_two_facts():
    pack = [_u(0, 'view'), _u(1, 'fact'), _u(2, 'fact'), _u(3, 'fact'), _u(4, 'mechanism'), _u(5, 'view')]
    out = compose.trim_judgment_pack(pack, keep=[pack[0]])
    kinds = [u['kind'] for u in out]
    assert kinds.count('fact') == 2
    assert kinds.count('view') == 1 and pack[0] in out
    assert 'mechanism' not in kinds


def test_trim_uses_mechanism_when_no_view():
    pack = [_u(1, 'fact'), _u(2, 'fact'), _u(3, 'fact'), _u(4, 'mechanism')]
    out = compose.trim_judgment_pack(pack)
    assert [u['kind'] for u in out].count('mechanism') == 1
    assert [u['kind'] for u in out].count('fact') == 2


def test_pick_units_judgment_pack_is_thin():
    pool = [_u(0, 'view'), *[_u(i, 'fact') for i in range(1, 6)], _u(9, 'mechanism')]
    chosen = compose.pick_units('judgment_take', pool)
    kinds = [u['kind'] for u in chosen]
    assert kinds.count('view') == 1
    assert kinds.count('fact') <= compose.JUDGMENT_MAX_FACTS
    assert len(chosen) <= 3


def test_compose_payload_carries_thesis_lock_and_evidence_budget():
    from tests.test_compose import SOURCE as CS, UNITS
    from tests.test_judgment import VIEW
    raw = dict(UNITS['units'][2], kind='view',
               view=dict(VIEW, reasoning=[UNITS['units'][2]['source_spans'][0]['exact_text']]))
    extra = [dict(UNITS['units'][0], statement=f'Fact copy {i}.') for i in range(3)]
    seen = {}

    class Fake:
        def __call__(self, stage, messages, max_tokens):
            p = json.loads(messages[-1]['content']); seen.setdefault(stage, p)
            if stage == 'extract':
                value = {'units': [UNITS['units'][0], UNITS['units'][1], *extra, raw]}
            elif stage == 'stance':
                value = {'decision': 'take', 'account_view': 'Memory supply looks tight.',
                         'supporting_unit_ids': [p['unit']['unit_id']], 'rationale': 'Supply discipline.',
                         'confidence': .7}
            else:
                value = {'body': 'Memory supply looks tight. Revenue was $54.23 billion.',
                         'claim_ledger': [{'claim': 'Revenue was $54.23 billion',
                                           'unit_id': next(u['unit_id'] for u in p['units'] if u['kind'] == 'fact'),
                                           'span_ref': 0}]}
            return {'text': json.dumps(value), 'finish_reason': 'stop'}

    result = compose.compose_source(CS, 'en_industry', Fake(), exemplars=False)
    assert result['post_type'] == 'judgment_take'
    payload = seen['compose']
    assert payload['thesis_lock'] == 'Memory supply looks tight.'
    assert payload['evidence_budget'] == {'max_numbers': 2, 'unused_units_ok': True}
    kinds = [u['kind'] for u in payload['units']]
    assert kinds.count('view') == 1 and kinds.count('fact') <= 2
    hard = payload['persona']['signature']['hard_constraints']
    assert any('at most 2 numbers' in h for h in hard)          # card-level constraint forwarded
    assert any('[data_take only]' in h for h in hard)
    assert 'MUST leave surplus units unused' in compose.COMPOSE


def test_no_thesis_lock_without_stance():
    from tests.test_compose import Fake, run

    class Spy(Fake):
        def __call__(self, stage, messages, max_tokens):
            if stage == 'compose':
                self.payload = json.loads(messages[-1]['content'])
            return super().__call__(stage, messages, max_tokens)

    spy = Spy()
    run(spy, post_type='data_take', account='zh_industry')
    assert 'thesis_lock' not in spy.payload and 'evidence_budget' not in spy.payload


# --- C. soft info_dump -----------------------------------------------------------------

def test_info_dump_soft_for_judgment_only():
    dump = '需求撑不住扩产。营收增长4.8倍，利润率69.5%，库存天数120天，资本开支300亿美元。'
    found = compose.info_dump_findings(dump, 'judgment_take')
    assert found and found[0]['code'] == 'info_dump'
    assert compose.info_dump_findings(dump, 'data_take') == []
    assert qa_levels.classify(found, frame_found=True)[0]['level'] == 'soft'
    clauses = 'Supply is the problem. Revenue 4.8x; margin 69.5%; capex 30.'
    assert compose.info_dump_findings(clauses, 'contrarian_take')
    thin = '需求高于供给这个方向能成立。利润率69.5%还撑得住，但扩产之后就难说了。'
    assert compose.info_dump_findings(thin, 'judgment_take') == []
