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
