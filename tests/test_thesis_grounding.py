"""Sentence-level thesis/grounding soft checks + fixed repair instructions."""
import json

from live import compose, qa_levels, thesis_grounding as tg
from tests.test_compose import SOURCE, UNITS, GOOD_BODY, Fake, run


def _stance(view='比特币对降息预期反应钝化，驱动力在链上资金流。', direction='neutral', subject='Bitcoin Fed hike odds'):
    return {'decision': 'adapt', 'account_view': view,
            'view': {'subject': subject, 'direction': direction, 'conviction': 'medium', 'horizon': 'weeks',
                     'reasoning': view}}


def _units(*statements):
    return [{'unit_id': f'cu-{i}', 'statement': s, 'source_spans': [{'exact_text': s}],
             'numbers': []} for i, s in enumerate(statements)]


def test_consensus_phrase_needs_consensus_evidence():
    body = '市场普遍认为比特币已经见顶，各方都在离场。'
    r = tg.review(body, _stance(), _units('Glassnode notes muted BTC reaction to hike odds.'), 'zh')
    assert 'UNSUPPORTED_CONSENSUS_CLAIM' in r['reason_codes']
    assert r['decision'] == 'REPAIR'
    assert 'market' in r['repair_instruction'].casefold() or '共识' in r['repair_instruction'] or 'consensus' in r['repair_instruction'].casefold()
    assert any(s['classification'] == 'UNGROUNDED_NEW_CLAIM' for s in r['spans'])


def test_en_consensus_and_analogy_as_evidence():
    units = _units('October hike odds fell from 66% to 22%. Bitcoin rose about 1% on the week.')
    body = ("Everyone is watching the Fed and the market expects a crash. "
            "Just like 2018 this proves the cycle top is in.")
    r = tg.review(body, _stance('Macro repricing is not driving Bitcoin right now.', 'neutral',
                                'Bitcoin price reaction to declining Fed hike odds'), units, 'en')
    assert 'UNSUPPORTED_CONSENSUS_CLAIM' in r['reason_codes']
    assert 'ANALOGY_AS_EVIDENCE' in r['reason_codes']
    assert '[grounding_repair]' in r['repair_instruction']


def test_supports_thesis_and_hedge_are_not_triggers():
    units = _units('PMI rose to 50.1%. Production index 51.7%. New orders 50.5%.')
    body = ('单月数据不足以确认趋势反转。'
            '如果后续流动性没有配合，韧性未必持续。'
            '生产指数达到51.7%。')
    r = tg.review(body, _stance('单月数据不足以确认趋势，需观察流动性配合。', 'neutral', '中国制造业产出'), units, 'zh')
    assert r['decision'] == 'PASS'
    classes = {s['classification'] for s in r['spans']}
    assert 'HEDGE' in classes or 'SUPPORTS_THESIS' in classes or 'NECESSARY_CONTEXT' in classes


def test_repair_instruction_families_are_fixed():
    text = tg.repair_instruction(['OFF_THESIS', 'UNSUPPORTED_NEW_CLAIM'], thesis_claim='keep this call')
    assert '[thesis_repair+grounding_repair]' in text or ('thesis_repair' in text and 'grounding_repair' in text)
    assert 'Frozen claim stays: keep this call' in text
    assert 'OFF_THESIS' not in text  # instructions, not raw codes dumped as the only content


def test_soft_finding_never_hard_blocks():
    assert 'thesis_grounding' in qa_levels.SOFT
    assert qa_levels.level({'code': 'thesis_grounding'}, frame_found=True) == 'soft'
    assert qa_levels.draft_status([{'code': 'thesis_grounding', 'level': 'soft'}]) == 'draft_ready'


def test_compose_retries_once_on_en_consensus_soft():
    """EN consensus overclaim triggers one soft repair/retry; never hard-blocks."""
    class Alternating(Fake):
        def __call__(self, stage, messages, max_tokens):
            self.calls.append(stage)
            if stage == 'extract':
                return {'text': json.dumps(self.units), 'finish_reason': 'stop', 'model': 'fake'}
            payload = json.loads(messages[-1]['content'])
            ids = [u['unit_id'] for u in payload['units']]
            n = self.calls.count('compose')
            # Use English GOOD-like body; first pass injects consensus wording.
            base = 'Revenue grew and margins held. The print does not clear the bar for a policy shift.'
            body = ('Everyone is watching and the market expects a crash. ' + base) if n == 1 else base
            ledger = [{'claim': 'revenue', 'unit_id': ids[0], 'span_ref': 0}]
            return {'text': json.dumps({'body': body, 'claim_ledger': ledger}),
                    'finish_reason': 'stop', 'model': 'fake'}

    result, fake = run(Alternating(), post_type='data_take', account='en_macro')
    assert fake.calls.count('compose') >= 2  # grounding retry; emotion may add another soft retry
    assert result.get('grounding_retry', {}).get('attempted') is True
    assert result['grounding_retry']['kept'] == 'retry'
    assert 'UNSUPPORTED_CONSENSUS_CLAIM' in result['grounding_retry']['first_reason_codes']
    assert 'Everyone is watching' not in result['body']
    assert result['draft_status'] == 'draft_ready'
    assert 'grounding_repair' in (result['grounding_retry'].get('repair_instruction') or '')
