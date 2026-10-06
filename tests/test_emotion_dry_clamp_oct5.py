"""PM relax 2026-10-05 eve: dry-source clamp for the soft emotion retry (MID/HIGH only)."""
import json

from live import emotion_contract as ec

DRY = [{'unit_id': '1', 'statement': 'Revenue was $54.23 billion in Q3.', 'source_spans': [], 'numbers': []}]
HOT = [{'unit_id': '1', 'statement': 'Crash! Panic dump, liquidations, nonsense, absurd crash, panic.',
        'source_spans': [], 'numbers': []}]
STANCE = {'account_view': 'Memory supply holds.'}
FLAT = 'Memory supply holds. Revenue was $54.23 billion.'
LIFTED = 'Memory supply holds. Revenue was $54.23 billion. Who sells? Why now? Too early, maybe wrong.'


def brief(account, units=DRY):
    return ec.build_emotion_brief(units, STANCE, lang='en', account_id=account)


def test_clamp_is_one_step_down_for_mid_and_high_only():
    high, mid, low = brief('trading_shortterm'), brief('en_industry'), brief('en_macro')   # v11: zh_* are low
    assert high['source_dry'] and high['target_intensity'] == 4 and high['accept_intensity'] == 3
    assert mid['source_dry'] and mid['target_intensity'] == 3 and mid['accept_intensity'] == 2
    assert low['accept_intensity'] == low['target_intensity']          # LOW never clamped


def test_no_clamp_when_source_is_not_dry_and_target_never_raised():
    for account in ('trading_shortterm', 'en_industry'):
        b = brief(account, HOT)
        assert not b['source_dry'] and b['accept_intensity'] == b['target_intensity']
        assert b['target_intensity'] == brief(account, HOT)['target_intensity']
    # Dry clamp does not lower the prompt target itself.
    assert brief('trading_shortterm')['target_intensity'] == 4


def test_high_retry_accepts_lower_target_on_dry_source():
    b = brief('trading_shortterm')
    first, retry = ec.emotion_findings(FLAT, b), ec.emotion_findings(LIFTED, b)
    assert first and retry and retry[0]['code'] == 'emotion_drop'      # finding still fires
    assert ec.draft_intensity(LIFTED, b) == 3 < b['target_intensity']
    assert ec.retry_improved(FLAT, LIFTED, b, 'en', first, retry) == ('dry_source_clamp', True)


def test_clamp_rejects_no_gain_and_overfire():
    b = brief('trading_shortterm')
    first = ec.emotion_findings(LIFTED, b)
    # Not strictly more intense than the first draft -> rejected.
    assert ec.retry_improved(LIFTED, LIFTED, b, 'en', first, first) == (None, False)
    hot = LIFTED + ' Crash! Panic! Dump! Absurd nonsense, lol.'
    assert ec.emotion_findings(hot, b) and ec.overfire_findings(hot, b, 'en')
    assert ec.draft_intensity(hot, b) > ec.draft_intensity(FLAT, b)
    assert ec.retry_improved(FLAT, hot, b, 'en', ec.emotion_findings(FLAT, b),
                             ec.emotion_findings(hot, b)) == (None, False)


def test_clamp_not_used_when_source_has_energy_or_tier_low():
    b = brief('trading_shortterm', HOT)
    first, retry = ec.emotion_findings(FLAT, b), ec.emotion_findings(LIFTED, b)
    assert ec.retry_improved(FLAT, LIFTED, b, 'en', first, retry) == (None, False)
    low = brief('en_macro')
    assert ec.dry_source_accepts(LIFTED, low) is False


def test_fewer_findings_still_wins():
    b = brief('trading_shortterm')
    good = 'Too early to call a glut. Revenue was $54.23 billion.'
    assert ec.retry_improved(FLAT, good, b, 'en', ec.emotion_findings(FLAT, b),
                             ec.emotion_findings(good, b)) == ('fewer_findings', True)


def test_clamp_keys_stay_out_of_model_payload():
    from tests.test_compose import Fake, run

    class Spy(Fake):
        def __call__(self, stage, messages, max_tokens):
            if stage == 'compose':
                self.payload = json.loads(messages[-1]['content'])
            return super().__call__(stage, messages, max_tokens)

    spy = Spy()
    result, _ = run(spy, post_type='data_take', account='zh_industry')
    sent = spy.payload['emotion_brief']
    assert 'accept_intensity' not in sent and 'source_dry' not in sent
    assert 'accept_intensity' in result['emotion_brief']
