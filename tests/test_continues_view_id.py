"""Structured continuity: each recorded call is exactly one of continue (continues_view_id, linked
deterministically from ledger match scores), revise (revises_view_id, model-set + validated) or
fresh (neither). Oct 5 eve sim: zh_macro day-2 PMI re-read was stored as a second near-identical
'current' view with no parent pointer; continuity only lived in prose (延续此前的观察)."""
import json

import pytest

from live import compose, view_ledger
from live.stance import STANCE, stance_step
from tests.test_compose import Fake, SOURCE


def call(subject='Bitcoin', direction='bearish', account_view='Bitcoin looks fragile into year end.',
         decision='take', conviction='medium', horizon='months', **extra):
    return {'decision': decision, 'account_view': account_view, 'confidence': 0.7, **extra,
            'view': {'subject': subject, 'direction': direction, 'conviction': conviction, 'horizon': horizon}}


class StanceClient:
    def __init__(self, answer):
        self.answer, self.payloads = answer, []

    def __call__(self, stage, messages, max_tokens):
        self.payloads.append(json.loads(messages[-1]['content']))
        return {'text': json.dumps(self.answer), 'finish_reason': 'stop', 'model': 'fake'}


UNIT = {'unit_id': 'cu-v', 'kind': 'view', 'statement': 'Bitcoin rally lacks ETF flow support.', 'speaker': 'Glassnode',
        'source_spans': [{'exact_text': 'Bitcoin rally lacks ETF flow support.'}], 'numbers': [],
        'view': {'subject': 'Bitcoin', 'direction': 'bearish', 'conviction': 'medium', 'horizon': 'weeks',
                 'reasoning': 'ETF flows are weak.', 'trace': [0]}}


def persona():
    from live import registry
    return registry.persona_for_account('crypto_macro_en')


def test_adapt_same_subject_and_direction_sets_continues_view_id(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    prior = led.record(call(), unit_ids=[], source_ids=[])
    client = StanceClient({'decision': 'adapt', 'account_view': 'Bitcoin stays fragile until ETF flows return.',
                           'supporting_unit_ids': ['cu-v'], 'rationale': 'same call, higher conviction', 'confidence': 0.7,
                           'continues_view_id': 'view-made-up-by-model',
                           'view': {'subject': 'Bitcoin', 'direction': 'bearish', 'conviction': 'high', 'horizon': 'weeks',
                                    'reasoning': 'ETF flows are weak.', 'trace': [0]}})
    out = stance_step(UNIT, persona(), client, ledger=led)
    assert out['decision'] == 'adapt'
    assert out['continues_view_id'] == prior['id'] and out['revises_view_id'] is None
    assert out['continuity']['link'] == 'continue' and out['continuity']['source'] == 'ledger_match'
    assert [f['code'] for f in out['ledger_findings']] == []
    e = led.record(out, unit_ids=['cu-v'], source_ids=['s2'])
    assert e['continues_view_id'] == prior['id'] and e['revises_view_id'] is None
    # The continued parent leaves current(); the chain head is the only lasting view.
    assert [r['id'] for r in led.current()] == [e['id']]
    assert led.lineage(e['id']) == [e['id'], prior['id']]


def test_revise_sets_revises_view_id_and_leaves_continues_empty(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    prior = led.record(call(), unit_ids=[], source_ids=[])
    client = StanceClient({'decision': 'adapt', 'account_view': 'Bitcoin now looks strong into year end as ETF flows return.',
                           'supporting_unit_ids': ['cu-v'], 'rationale': 'flows turned; I revise my bearish call',
                           'confidence': 0.6, 'revises_view_id': prior['id'],
                           'view': {'subject': 'Bitcoin', 'direction': 'bullish', 'conviction': 'medium', 'horizon': 'weeks',
                                    'reasoning': 'ETF flows are weak.', 'trace': [0]}})
    out = stance_step(UNIT, persona(), client, ledger=led)
    assert out['revises_view_id'] == prior['id'] and out['continues_view_id'] is None
    assert out['continuity'] == {'link': 'revise', 'source': 'model', 'view_id': prior['id']}
    assert out['ledger_findings'] == []
    e = led.record(out, unit_ids=['cu-v'], source_ids=['s2'])
    assert (e['revises_view_id'], e['continues_view_id']) == (prior['id'], None)


def test_fresh_take_has_neither_link(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    led.record(call(subject='Gold', direction='bullish', account_view='Gold keeps grinding higher on central bank buying.'),
               unit_ids=[], source_ids=[])
    client = StanceClient({'decision': 'take', 'account_view': 'Bitcoin rally is thin without ETF flows.',
                           'supporting_unit_ids': ['cu-v'], 'rationale': 'adopt', 'confidence': 0.6})
    out = stance_step(UNIT, persona(), client, ledger=led)
    assert out['continues_view_id'] is None and out['revises_view_id'] is None
    assert out['continuity']['link'] == 'fresh'
    e = led.record(out, unit_ids=['cu-v'], source_ids=['s2'], input_view=UNIT['view'])
    assert (e['continues_view_id'], e['revises_view_id']) == (None, None)
    # Empty ledger: also fresh
    out2 = view_ledger.ViewLedger('empty', tmp_path).link_continuity(call(), [])
    assert (out2['continues_view_id'], out2['revises_view_id'], out2['continuity']['link']) == (None, None, 'fresh')


def test_take_without_view_continues_via_input_view(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    prior = led.record(call(), unit_ids=[], source_ids=[])
    client = StanceClient({'decision': 'take', 'account_view': 'Bitcoin rally is still fragile without ETF flows.',
                           'supporting_unit_ids': ['cu-v'], 'rationale': 'adopt', 'confidence': 0.6})
    out = stance_step(UNIT, persona(), client, ledger=led)
    assert out['continues_view_id'] == prior['id']


def test_unacknowledged_flip_is_not_a_continuation(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    prior = led.record(call(), unit_ids=[], source_ids=[])
    out = led.link_continuity(call(direction='bullish', account_view='Bitcoin looks strong into year end.'))
    assert out['continues_view_id'] is None and out['revises_view_id'] is None
    assert out['continuity'] == {'link': 'fresh', 'source': 'ledger_match', 'unacknowledged_flip_of': prior['id']}
    assert [f['code'] for f in led.contradictions(out)] == ['contradicts_prior_view']


def test_mutual_exclusion(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    prior = led.record(call(), unit_ids=[], source_ids=[])
    # record refuses both links
    with pytest.raises(ValueError, match='not both'):
        led.record(call(continues_view_id=prior['id'], revises_view_id=prior['id']), unit_ids=[], source_ids=[])
    # linker: a model revise wins and clears any continue
    out = led.link_continuity(call(revises_view_id=prior['id'], continues_view_id=prior['id']))
    assert (out['revises_view_id'], out['continues_view_id']) == (prior['id'], None)
    # unknown ids are never persisted
    with pytest.raises(ValueError, match='not a recorded view'):
        led.record(call(continues_view_id='view-nope'), unit_ids=[], source_ids=[])
    # reject: no links at all
    rej = led.link_continuity({'decision': 'reject', 'account_view': '', 'revises_view_id': prior['id']})
    assert (rej['revises_view_id'], rej['continues_view_id']) == (None, None)


def test_cited_prior_breaks_ties_and_bad_citations_are_dropped(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    a = led.record(call(subject='Bitcoin', account_view='Bitcoin looks fragile into year end.'), unit_ids=[], source_ids=[])
    b = led.record(call(subject='Bitcoin', account_view='Bitcoin looks fragile into year end.'), unit_ids=[], source_ids=[])
    rows = led.related('Bitcoin fragile year end', k=5)
    assert led.link_continuity(call(), rows)['continues_view_id'] == b['id']   # latest wins a plain tie
    assert led.link_continuity(call(cited_prior_view_ids=[a['id']]), rows)['continues_view_id'] == a['id']
    client = StanceClient({'decision': 'take', 'account_view': 'Bitcoin rally is still fragile without ETF flows.',
                           'supporting_unit_ids': ['cu-v'], 'rationale': 'adopt', 'confidence': 0.6,
                           'cited_prior_view_ids': ['view-fake', a['id']]})
    out = stance_step(UNIT, persona(), client, ledger=led)
    assert out['cited_prior_view_ids'] == [a['id']] and out['continues_view_id'] == a['id']


def test_oct5_trading_shortterm_pair_links(tmp_path):
    """Real R1/R2 subjects from /workspace/x/ledger_sim_oct5_eve (subject wording drifted between rounds)."""
    led = view_ledger.ViewLedger('trading_shortterm', tmp_path)
    r1 = led.record(call(subject='Systematic de-risking vulnerability into midterm elections', direction='higher',
                         horizon='days', account_view='Unusually low VIX curve pricing ahead of the midterms leaves the '
                         'market vulnerable to systematic de-risking if macro overhangs force a sudden volatility spike.'),
                    unit_ids=[], source_ids=[])
    r2 = call(subject='systematic de-risking triggered by steepening index put skew and rising VIX', direction='higher',
              decision='adapt', conviction='high', horizon='days',
              account_view='With TLT skew maxed at 100 while SPY IV sits at yearly lows, a sudden steepening in index put '
                           'skew alongside a rising VIX will confirm rates contagion and ignite the systematic de-risking '
                           'vulnerability we previously flagged.')
    assert led.link_continuity(r2)['continues_view_id'] == r1['id']


def test_compose_supplied_stance_links_on_record(tmp_path):
    led = view_ledger.ViewLedger('zh_industry', tmp_path)
    stance = {'decision': 'take', 'account_view': '存储供给偏紧会延续。', 'confidence': 0.7, 'supporting_unit_ids': [],
              'view': {'subject': 'memory supply', 'direction': 'tighter', 'conviction': 'medium', 'horizon': 'quarters'}}
    r = compose.compose_source(SOURCE, 'zh_industry', Fake(), post_type='data_take', stance_output=stance, view_ledger=led)
    assert r['draft_status'] == 'draft_ready'
    first = led.entries()[-1]
    assert first['continues_view_id'] is None
    again = dict(stance, account_view='存储供给偏紧还会延续一个季度。')
    r2 = compose.compose_source(SOURCE, 'zh_industry', Fake(), post_type='data_take', stance_output=again, view_ledger=led)
    assert r2['draft_status'] == 'draft_ready'
    second = led.entries()[-1]
    assert second['continues_view_id'] == first['id'] and r2['stance']['continuity']['link'] == 'continue'
    assert [e['id'] for e in led.current()] == [second['id']]


def test_prompt_documents_links():
    assert 'Do not output continues_view_id' in STANCE and 'cited_prior_view_ids' in STANCE
    assert 'revises_view_id: optional prior view id' in STANCE
