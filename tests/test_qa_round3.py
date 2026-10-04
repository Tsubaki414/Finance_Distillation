"""Round-three compliance, consistency and transport retry regressions."""
import pytest
from live import compose, qa_levels
from live.distillation import ContractError
from tests.test_compose import Fake, GOOD_BODY, run

@pytest.mark.parametrize('body,lang', [
    ('Consider a 20-cent QQQ put fly 1% OTM in 1-5 DTE.', 'en'),
    ('Buy NVDA at 120 with a stop at 110.', 'en'),
    ('可以在3200点附近买入沪深300ETF，止损3100。', 'zh'),
    ('做多BTC，目标价12万。', 'zh'),
])
def test_specific_trade(body, lang):
    assert {f['code'] for f in compose.trade_reco_findings(body, lang)} == {'trade_reco_specific'}

@pytest.mark.parametrize('body,lang', [('Consider adding QQQ exposure.', 'en'), ('可以关注美债。', 'zh')])
def test_soft_trade(body, lang):
    findings = compose.trade_reco_findings(body, lang)
    assert findings and qa_levels.classify(findings, frame_found=True)[0]['level'] == 'soft'

@pytest.mark.parametrize('body', ['I expect yields to rise.', 'bearish on semis into earnings', '看空美债',
    'Goldman recommends buying NVDA at 120 with a stop at 110.', '高盛建议在3200点买入沪深300ETF。'])
def test_trade_negative(body):
    assert compose.trade_reco_findings(body, 'en') == []

@pytest.mark.parametrize('body', ['True Market Mean of $73.3K. True Market Mean at $77.2K.',
    'PMI 50.1% ，PMI 49.8%。', '营业利润率为60%。营业利润率为65%。',
    '$73.3K True Market Mean. $77.2K True Market Mean.'])
def test_contradiction(body):
    assert compose.contradiction_findings(body)

@pytest.mark.parametrize('body', ['Margin rose from 66% to 22%.', 'PMI从49.8%升至50.1%。',
    'PMI range 49.8%-50.1%.', 'PMI 50.1% vs 49.8%.',
    'Q1 PMI 50.1%. Q2 PMI 49.8%.', 'January PMI 50.1%. February PMI 49.8%.',
    'PMI 50.1%. PMI 50.2%.', 'PMI 50.1%，前值49.8%。'])
def test_contradiction_negative(body):
    assert compose.contradiction_findings(body) == []

class Sequence:
    def __init__(self, outputs): self.outputs = iter(outputs); self.count = 0
    def __call__(self, *args):
        self.count += 1
        result = next(self.outputs)
        if isinstance(result, Exception): raise result
        return result

OK = {'text': '{"ok": true}', 'finish_reason': 'stop'}
@pytest.mark.parametrize('bad', [{'text': '{', 'finish_reason': 'stop'},
    {'text': '{}', 'finish_reason': 'length'}, OSError('temporary'), TimeoutError('temporary')])
@pytest.mark.parametrize('stage', ['compose', 'stance'])
def test_retry_then_valid(bad, stage):
    client = Sequence([bad, OK]); calls = []; sleeps = []
    value, _ = compose._ask(client, stage, 'Return JSON.', {}, 100, calls, sleep=sleeps.append)
    assert value == {'ok': True} and client.count == 2
    assert sleeps == [0.5] and calls[0]['attempts'] == 2

@pytest.mark.parametrize('bad', [{'text': '{', 'finish_reason': 'stop'}, OSError('temporary')])
def test_retry_exhausted(bad):
    client = Sequence([bad] * 3); calls = []; sleeps = []
    with pytest.raises(ContractError):
        compose._ask(client, 'compose', 'Return JSON.', {}, 100, calls, sleep=sleeps.append)
    assert client.count == 3 and sleeps == [0.5, 1.0] and calls[0]['attempts'] == 3

def test_content_error_not_retried():
    client = Sequence([ContractError('grounding error'), OK])
    with pytest.raises(ContractError):
        compose._ask(client, 'compose', 'Return JSON.', {}, 100, [], sleep=lambda _: None)
    assert client.count == 1

def test_refusal_not_retried():
    client = Sequence([{**OK, 'refusal': 'no'}, OK])
    with pytest.raises(ContractError):
        compose._ask(client, 'compose', 'Return JSON.', {}, 100, [], sleep=lambda _: None)
    assert client.count == 1

def test_wired_levels():
    hard, _ = run(Fake(body=GOOD_BODY + '做多BTC，目标价12万。'), post_type='data_take')
    assert 'trade_reco_specific' in hard['qa']['hard']
    soft, _ = run(Fake(body=GOOD_BODY + '可以关注美债。'), post_type='data_take')
    assert 'trade_reco_soft' in soft['qa']['soft'] and soft['draft_status'] == 'draft_ready'
    conflicting, _ = run(Fake(body=GOOD_BODY + 'PMI 50.1%。PMI 49.8%。'), post_type='data_take')
    assert 'self_contradiction' in conflicting['qa']['hard']

@pytest.mark.parametrize('content_error', [False, True])
def test_stance_entry_retry(content_error, monkeypatch):
    import json
    from live import stance
    monkeypatch.setattr(stance, 'validate_view', lambda value, *args, **kwargs: value)
    view = {'horizon': 'short_term'}
    unit = {'unit_id': 'cu-view', 'view': view, 'source_spans': []}
    persona = {'stance': {'horizon': 'short_term'}}
    valid = {'decision': 'take', 'account_view': 'Yields will rise',
             'supporting_unit_ids': ['cu-view'], 'rationale': 'Supported view', 'confidence': 0.8}
    bad = {'text': json.dumps({**valid, 'confidence': 2}) if content_error else '{',
           'finish_reason': 'stop'}
    client = Sequence([bad, {'text': json.dumps(valid), 'finish_reason': 'stop'}])
    calls = []; sleeps = []
    if content_error:
        with pytest.raises(ContractError):
            stance.stance_step(unit, persona, client, calls=calls, sleep=sleeps.append)
        assert client.count == 1 and sleeps == []
    else:
        result = stance.stance_step(unit, persona, client, calls=calls, sleep=sleeps.append)
        assert result['decision'] == 'take' and calls[0]['attempts'] == 2 and sleeps == [0.5]

@pytest.mark.parametrize('message', ['compose: incomplete/unknown finish_reason', 'compose: malformed JSON'])
def test_client_transport_contract_retry(message):
    client = Sequence([ContractError(message), OK]); calls = []
    assert compose._ask(client, 'compose', 'Return JSON.', {}, 100, calls, sleep=lambda _: None)[0]['ok']
    assert calls[0]['attempts'] == 2

def test_no_specific_level_in_year_or_instrument_name():
    for body in ['Buy NVDA ahead of 2026 earnings.', '可以关注沪深300ETF。']:
        assert {f['code'] for f in compose.trade_reco_findings(body, 'en')} == {'trade_reco_soft'}
