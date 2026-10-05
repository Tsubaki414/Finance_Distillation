"""ZH over-claim: expanded certainty patterns + restraint snippets on signature cards."""
from live import compose, registry


def test_zh_crowd_wording_flags_certainty_overreach():
    stance = {'account_view': '稳定币叠加主权背书会带来监管摩擦。', 'view': {}}
    units = [{'statement': '萨尔瓦多签了一份5年期合同。', 'source_spans': []}]
    body = '稳定币叠加主权背书。但很显然，各方都成了惊弓之鸟。'
    out = compose.certainty_findings(body, units, stance, 'zh')
    assert out and out[0]['code'] == 'certainty_overreach'
    assert '各方都' in out[0]['detail'] or '惊弓之鸟' in out[0]['detail']


def test_zh_absolute_still_flagged_when_not_in_units():
    stance = {'account_view': '降息预期的边际变化已经钝化。', 'view': {}}
    units = [{'statement': '加息概率从66%降到22%。', 'source_spans': []}]
    assert compose.certainty_findings('降息预期的边际变化已经彻底钝化。', units, stance, 'zh')


def test_zh_clean_conditional_call_is_not_flagged():
    stance = {'account_view': '单月数据不足以确认趋势反转。', 'view': {}}
    units = [{'statement': '制造业PMI升至50.1%。', 'source_spans': []}]
    body = '单月数据不足以确认制造业趋势反转。\n我的判断：不要对市场进行线性外推。'
    assert compose.certainty_findings(body, units, stance, 'zh') == []


def test_signature_cards_carry_zh_restraint_snippets():
    for pid in ('zh_macro', 'zh_industry', 'crypto_macro_zh'):
        p = registry.persona_for_account(pid)
        snips = (p.signature_card or {}).get('zh_restraint') or []
        assert len(snips) >= 3, pid
        assert all(s.get('text') and s.get('id') for s in snips)


def test_zh_compose_retries_once_on_certainty_overreach():
    """First body overclaims; retry cleans it. Soft path — never hard-blocks."""
    import json
    from tests.test_compose import SOURCE, UNITS, GOOD_BODY, Fake, run

    class Alternating(Fake):
        def __call__(self, stage, messages, max_tokens):
            self.calls.append(stage)
            if stage == 'extract':
                return {'text': json.dumps(self.units), 'finish_reason': 'stop', 'model': 'fake'}
            payload = json.loads(messages[-1]['content'])
            ids = [u['unit_id'] for u in payload['units']]
            n = self.calls.count('compose')
            body = ('各方都成了惊弓之鸟，监管摩擦一定会出现。' + GOOD_BODY) if n == 1 else GOOD_BODY
            ledger = [{'claim': '营收与利润率', 'unit_id': ids[0], 'span_ref': 0}]
            return {'text': json.dumps({'body': body, 'claim_ledger': ledger}, ensure_ascii=False),
                    'finish_reason': 'stop', 'model': 'fake'}

    result, fake = run(Alternating(), post_type='data_take', account='zh_industry')
    assert fake.calls.count('compose') == 2
    assert result.get('certainty_retry', {}).get('attempted') is True
    assert result['certainty_retry']['kept'] == 'retry'
    assert 'certainty_overreach' not in {f['code'] for f in result['post_checks']}
    assert '惊弓之鸟' not in result['body']
