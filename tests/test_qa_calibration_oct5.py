import json
import pytest
from live import compose, emotion_contract as ec, thesis_grounding as tg, qa_levels
from tests.test_compose import Fake, GOOD_BODY, SOURCE, run

@pytest.mark.parametrize('body', ['不一定会反弹', '并非所有资产', '不完全是', '不是每次', '未必彻底', '并不绝对', '一定程度上', '有一定的规模', '绝对收益', '所有权', '完全取决于数据'])
def test_zh_hedges(body):
    assert compose.certainty_findings(body, [], {}, 'zh') == []

@pytest.mark.parametrize('body', ['not entirely', "isn't guaranteed", 'far from certain', 'not necessarily always', 'by no means completely', 'no longer guaranteed'])
def test_en_hedges(body):
    assert compose.certainty_findings(body, [], {}, 'en') == []

@pytest.mark.parametrize('word', ['毫无疑问', '史无前例', '众所周知'])
def test_new_lexicon(word):
    assert compose.certainty_findings(word, [], {}, 'zh')

def test_cross_language():
    assert not compose.certainty_findings('史无前例，前所未有', [{'statement': 'unprecedented'}], {}, 'zh')

@pytest.mark.parametrize('lang,soft,strong', [('en', 'will', 'bound to'), ('zh', '将会', '必将')])
def test_forward_call(lang, soft, strong):
    stance = {'view': {'direction': 'up', 'horizon': 'one month'}}
    assert not compose.certainty_findings(soft, [], stance, lang)
    assert compose.certainty_findings(soft, [], {}, lang)
    assert compose.certainty_findings(strong, [], stance, lang)

@pytest.mark.parametrize('lang,body', [('zh', '不是大家都在看'), ('zh', '并非市场普遍认为会上涨'), ('en', 'not everyone is watching'), ('en', 'it is not widely believed')])
def test_negated_consensus(lang, body):
    assert 'UNSUPPORTED_CONSENSUS_CLAIM' not in tg.review(body, {}, [], lang)['reason_codes']

def test_contrarian_consensus():
    assert 'UNSUPPORTED_CONSENSUS_CLAIM' in tg.review('市场普遍认为会上涨，但我不认同', {}, [], 'zh')['reason_codes']

@pytest.mark.parametrize('body', ['Lots of dovish talk about a Fed pause, but it is mostly recency bias.', '这个资产被高估。'])
def test_judgment_reaction(body):
    assert ec.first_two_have_reaction(body)

def test_tier_targets():
    dry = [{'statement': 'Data was released.'}]
    heated = [{'statement': 'panic panic panic panic panic!!'}]
    assert ec.tier_policy('crypto_macro_zh')['target_intensity_max'] == 4
    assert ec.build_emotion_brief(dry, {}, tier='high')['target_intensity'] == 4
    assert ec.build_emotion_brief(heated, {}, tier='high')['target_intensity'] == 5
    assert ec.build_emotion_brief(dry, {}, tier='mid')['target_intensity'] == 3
    assert ec.build_emotion_brief(dry, {}, tier='low')['target_intensity'] == 2
    assert ec.build_emotion_brief(heated, {}, tier='low')['target_intensity'] == 3

@pytest.mark.parametrize('body', ['Data!!!', 'Panic! Crash! Dump! Nonsense.', 'Data 😀🔥'])
def test_overfire(body):
    findings = ec.overfire_findings(body, {'target_intensity': 2, 'tier': 'low'}, 'en')
    assert findings and qa_levels.classify(findings, frame_found=True)[0]['level'] == 'soft'

def test_calm_and_absent_brief():
    assert not ec.overfire_findings('This looks premature.', {'target_intensity': 3}, 'en')
    # Restrained judgment openings from real drafts are not overfire (old intensity rule flagged them).
    assert not ec.overfire_findings('单月数据不足以确认趋势，不要对市场进行线性外推。', {'target_intensity': 3, 'tier': 'mid'}, 'zh')
    assert not ec.overfire_findings('Calling the end of the cycle on a single print is pure recency bias.',
                                    {'target_intensity': 2, 'tier': 'low'}, 'en')


def test_high_wary_source_caps_at_4():
    wary = [{'statement': 'Risk risk risk: watch the overhang, caution, wary of risk.'}]
    assert ec.build_emotion_brief(wary, {}, tier='high')['target_intensity'] == 4
    assert not ec.overfire_findings('!!!', None, 'zh')

class RetryFake(Fake):
    def __call__(self, stage, messages, max_tokens):
        if stage == 'compose':
            payload = json.loads(messages[-1]['content'])
            note = payload.get('rewrite_note', '')
            self.body = ('大家都在恐慌。' + GOOD_BODY if 'emotion_repair' in note else
                         '被高估，供给偏紧。' + GOOD_BODY if 'judgment_repair' in note else
                         '营收同比增长4.8倍，达到542.3亿美元，营业利润率为69.5%。')
        return super().__call__(stage, messages, max_tokens)

def test_emotion_guard_and_judgment_priority():
    result, _ = run(RetryFake(), post_type='data_take', account='crypto_macro_zh')
    retry = result['emotion_retry']
    assert retry['kept'] == 'original'
    assert retry['reject_reason'] == 'guard_regression'
    assert retry['new_guard_codes']
    assert '大家都在恐慌' not in result['body']


def test_judgment_retry_keeps_improvement():
    result = compose.compose_source(SOURCE, 'zh_industry', RetryFake(), post_type='data_take',
                                    stance_output={'decision': 'adapt', 'account_view': '供给偏紧，被高估。'})
    assert result['judgment_retry']['kept'] == 'retry'


@pytest.mark.parametrize('word', ['never', 'nothing', 'nobody'])
def test_negative_absolutes_remain_absolutes(word):
    assert compose.certainty_findings('not ' + word, [], {}, 'en')

@pytest.mark.parametrize('body', ['not very likely guaranteed', 'Never entirely certain. But entirely wrong.', '不完全是，但完全错了'])
def test_scope_does_not_hide_later_absolute(body):
    assert compose.certainty_findings(body, [], {}, 'zh' if '不' in body else 'en')

@pytest.mark.parametrize('body', ['not quite entirely', 'hardly ever guaranteed', 'not really always'])
def test_one_adverb_negation(body):
    assert not compose.certainty_findings(body, [], {}, 'en')

class SequenceFake(Fake):
    def __init__(self, bodies):
        super().__init__()
        self.bodies = iter(bodies)

    def __call__(self, stage, messages, max_tokens):
        if stage == 'compose':
            self.body = next(self.bodies)
        return super().__call__(stage, messages, max_tokens)


def test_emotion_retry_requires_improvement():
    original = '营收同比增长4.8倍，达到542.3亿美元，营业利润率为69.5%。'
    result, _ = run(SequenceFake([original, original + '美光披露数据。']), post_type='data_take', account='crypto_macro_zh')
    assert result['emotion_retry']['kept'] == 'original'
    assert result['emotion_retry']['reject_reason'] == 'no_improvement'
    assert result['body'] == original


def test_judgment_improvement_records_guard_regression():
    original = '营收同比增长4.8倍，达到542.3亿美元，营业利润率为69.5%。'
    retry = '供给偏紧，被高估。大家都在恐慌。' + GOOD_BODY
    result = compose.compose_source(SOURCE, 'zh_industry', SequenceFake([original, retry]), post_type='data_take',
                                    stance_output={'decision': 'adapt', 'account_view': '供给偏紧，被高估。'})
    assert result['body'] == retry
    assert result['judgment_retry']['kept'] == 'retry'
    assert 'certainty:大家都在' in result['judgment_retry']['guard_regression']


def test_judgment_retry_requires_improvement():
    original = '营收同比增长4.8倍，达到542.3亿美元，营业利润率为69.5%。'
    result = compose.compose_source(SOURCE, 'zh_industry', SequenceFake([original, original]), post_type='data_take',
                                    stance_output={'decision': 'adapt', 'account_view': '供给偏紧，被高估。'})
    assert result['judgment_retry']['kept'] == 'original'
    assert result['judgment_retry']['reject_reason'] == 'no_improvement'


def test_grounding_retry_rejects_code_swap():
    original = '市场普遍认为供给偏紧。' + GOOD_BODY
    result = compose.compose_source(SOURCE, 'zh_industry', SequenceFake([original, '就像以前一样证明供给偏紧。' + GOOD_BODY]),
                                    post_type='data_take', emotion_contract=False)
    assert result['grounding_retry']['kept'] == 'original'
    assert result['grounding_retry']['reject_reason'] == 'guard_regression'
    assert result['body'] == original


def test_low_tier_runs_overfire_post_check():
    result, _ = run(Fake(body='This looks premature!!!'), post_type='data_take', account='en_macro')
    assert result['emotion_brief']['tier'] == 'low'
    assert 'emotion_overfire' in {f['code'] for f in result['post_checks']}
    assert all(f['level'] == 'soft' for f in result['post_checks'] if f['code'] == 'emotion_overfire')


@pytest.mark.parametrize('body', [
    'Bitcoin is shrugging off the macro repricing.',
    'Vol screens cheap into the midterm and the VIX curve has been asleep at the wheel.',
    'Front-running bond market contagion is a mistake until the equity surface confirms it.',
    '当前比特币的定价逻辑根本不在货币政策预期。',
    '比特币对降息预期已经免疫了。',
])
def test_attitude_openings_count_as_reaction(body):
    """Real HIGH-tier openings that already react must not trigger an emotion retry."""
    assert ec.first_two_have_reaction(body)


def test_calm_recap_still_lacks_reaction():
    assert not ec.first_two_have_reaction('Rate expectations are not driving Bitcoin right now. Odds fell from 66% to 22%.')
