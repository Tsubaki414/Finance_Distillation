"""Oct 6 P1-1 follow-ups (soft-only, never block):
1. stance prompt: same direction + only horizon/conviction change = continue; revise = direction or core thesis.
2. direction_drift_unmarked: cited/on-topic prior, different (non-opposite) direction, no revises_view_id ->
   linked as drift_of_view_id (supersedes the prior) + SOFT finding, not a silent 2nd current entry.
3. meta-continuation openers scrubbed from account_view and soft-banned in drafts."""
import pytest

from live import qa_levels, view_ledger
from live.compose import template_patterns
from live.stance import STANCE, scrub_account_view, stance_cadence_findings, stance_step
from tests.test_continues_view_id import StanceClient, UNIT, call, persona


FED = dict(subject='Federal Reserve interest rate hike probability', direction='lower',
           account_view='Soft September payrolls lower the odds of another Fed hike this year.')


def adapt(direction, *, cited=None, revises=None, horizon='weeks', conviction='medium',
          account_view='Bitcoin stays range-bound until ETF flows return.'):
    answer = {'decision': 'adapt', 'account_view': account_view, 'supporting_unit_ids': ['cu-v'],
              'rationale': 'carried forward', 'confidence': 0.7,
              'view': {'subject': 'Bitcoin', 'direction': direction, 'conviction': conviction, 'horizon': horizon,
                       'reasoning': 'ETF flows are weak.', 'trace': [0]}}
    if cited is not None:
        answer['cited_prior_view_ids'] = cited
    if revises is not None:
        answer['revises_view_id'] = revises
    return StanceClient(answer)


# 1. prompt rule ---------------------------------------------------------------------------------
def test_stance_prompt_states_continue_vs_revise_rule_and_bans_meta_openers():
    assert 'SAME direction, even if horizon or conviction' in STANCE
    assert 'do NOT set revises_view_id' in STANCE
    assert 'core thesis' in STANCE and 'MUST set revises_view_id' in STANCE
    assert 'continuity phrase' not in STANCE           # the old wording taught "Continuing ..."
    assert '延续此前判断' in STANCE and 'As I said' in STANCE


def test_same_direction_revise_is_kept_but_marked_for_review(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    prior = led.record(call(), unit_ids=[], source_ids=[])          # Bitcoin bearish
    out = stance_step(UNIT, persona(), adapt('bearish', revises=prior['id'], conviction='high'), ledger=led)
    assert out['continuity']['link'] == 'revise' and out['continuity']['same_direction'] is True


# 2. direction drift -----------------------------------------------------------------------------
def test_cited_prior_with_drifted_direction_links_drift_and_soft_finding(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    prior = led.record(call(), unit_ids=[], source_ids=[])          # bearish
    out = stance_step(UNIT, persona(), adapt('neutral', cited=[prior['id']]), ledger=led)
    assert out['drift_of_view_id'] == prior['id']
    assert out['continues_view_id'] is None and out['revises_view_id'] is None
    assert out['continuity'] == {'link': 'drift', 'source': 'ledger_match', 'view_id': prior['id'],
                                 'from_direction': 'bearish', 'to_direction': 'neutral'}
    codes = [f['code'] for f in out['ledger_findings']]
    assert codes == ['direction_drift_unmarked']
    assert qa_levels.classify(out['ledger_findings'], frame_found=True)[0]['level'] == 'soft'   # never blocks
    entry = led.record(out, unit_ids=['cu-v'], source_ids=['s2'])
    assert entry['drift_of_view_id'] == prior['id']
    assert [r['id'] for r in led.current()] == [entry['id']]       # one head for the topic
    assert led.lineage(entry['id']) == [entry['id'], prior['id']]


def test_oct6_en_macro_lower_to_neutral_is_drift_not_fresh(tmp_path):
    led = view_ledger.ViewLedger('en_macro', tmp_path)
    prior = led.record(call(**FED), unit_ids=[], source_ids=[])
    stance = {'decision': 'adapt', 'cited_prior_view_ids': [prior['id']],
              'account_view': 'The Fed holds for several more months while core PCE stays at 3.0%.',
              'view': {'subject': 'Federal Reserve interest rate policy', 'direction': 'neutral'}}
    out = led.link_continuity(stance, prior_rows=led.related('Federal Reserve interest rate policy'))
    assert out['continuity']['link'] == 'drift' and out['drift_of_view_id'] == prior['id']


def test_uncited_off_subject_direction_change_stays_fresh(tmp_path):
    led = view_ledger.ViewLedger('en_macro', tmp_path)
    led.record(call(**FED), unit_ids=[], source_ids=[])
    stance = {'decision': 'take', 'account_view': 'Treasury term premium keeps rising on supply.',
              'view': {'subject': 'US Treasury term premium', 'direction': 'higher'}}
    out = led.link_continuity(stance)
    assert out['continuity']['link'] == 'fresh' and out['drift_of_view_id'] is None
    assert led.drift_findings(out) == []


def test_opposite_direction_is_still_a_flip_not_a_drift(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    prior = led.record(call(), unit_ids=[], source_ids=[])          # bearish
    out = stance_step(UNIT, persona(), adapt('bullish', cited=[prior['id']],
                                            account_view='Bitcoin breaks higher once ETF flows return.'), ledger=led)
    assert out['continuity']['link'] == 'fresh' and out['drift_of_view_id'] is None
    assert 'contradicts_prior_view' in [f['code'] for f in out['ledger_findings']]


def test_same_direction_horizon_change_still_continues(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    prior = led.record(call(), unit_ids=[], source_ids=[])          # bearish, months
    out = stance_step(UNIT, persona(), adapt('bearish', cited=[prior['id']], horizon='quarters'), ledger=led)
    assert out['continues_view_id'] == prior['id'] and out['continuity']['link'] == 'continue'


def test_record_refuses_two_links(tmp_path):
    led = view_ledger.ViewLedger('crypto_macro_en', tmp_path)
    prior = led.record(call(), unit_ids=[], source_ids=[])
    with pytest.raises(ValueError):
        led.record(dict(call(), continues_view_id=prior['id'], drift_of_view_id=prior['id']),
                   unit_ids=[], source_ids=[])
    with pytest.raises(ValueError):
        led.record(dict(call(), drift_of_view_id='view-unknown'), unit_ids=[], source_ids=[])


# 3. meta-continuation openers -------------------------------------------------------------------
@pytest.mark.parametrize('text,expected', [
    ('Continuing the expectation that policy shifts demand persistent evidence, the Fed holds for months.',
     'The Fed holds for months.'),
    ('Following up on last week, payroll weakness keeps the Fed on hold.', 'Payroll weakness keeps the Fed on hold.'),
    ('As I said before, the Fed will hold.', 'The Fed will hold.'),
    ('延续此前的判断，美联储短期内按兵不动。', '美联储短期内按兵不动。'),
    ('接着上次的话题，英伟达的护城河还在。', '英伟达的护城河还在。'),
])
def test_meta_continuation_opener_is_scrubbed(text, expected):
    out, meta = scrub_account_view(text)
    assert out == expected and meta['meta_continuation'] and meta['hits_after'] == []


def test_mid_sentence_meta_phrase_is_a_soft_cadence_finding_not_a_strip():
    out, meta = scrub_account_view('英伟达护城河仍在，正如我之前说的那样不会被商品化。')
    assert meta['hits_after'] == ['正如我之前说']             # triggers the existing stance_scrub retry
    assert stance_cadence_findings(out)[0]['code'] == 'stance_cadence'


def test_substantive_continuing_is_not_flagged():
    out, meta = scrub_account_view('Continuing weakness in payrolls will force the Fed to pause.')
    assert out.startswith('Continuing weakness') and not meta['meta_continuation']


@pytest.mark.parametrize('lang,body', [
    ('en', 'Continuing the expectation that soft data matters, the Fed holds.'),
    ('en', 'As I said, the Fed holds.'),
    ('zh', '延续此前判断，美联储会按兵不动。'),
    ('zh', '正如我之前说的，美联储会按兵不动。'),
])
def test_drafts_soft_ban_meta_continuation(lang, body):
    hits = [show for show, rx in template_patterns(lang) if rx.search(body)]
    assert hits and qa_levels.level({'code': 'template_phrase'}, frame_found=True) == 'soft'
