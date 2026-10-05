"""Per-persona emotion tiers: HIGH retries, MID warns, LOW restrained."""
import json

from live import emotion_contract as ec
from tests.test_compose import Fake, GOOD_BODY, run


def test_all_personas_mapped_to_tiers():
    cfg = json.loads(ec.TIERS_PATH.read_text())
    expected = {
        'crypto_macro_zh', 'crypto_macro_en', 'trading_shortterm', 'market_data_charts',
        'zh_macro', 'zh_industry', 'en_industry',
        'en_macro', 'investing_philosophy', 'single_stock_deepdive_en', 'en_morris_archive',
    }
    assert expected <= set(cfg['personas'])
    for aid in ('crypto_macro_zh', 'crypto_macro_en', 'trading_shortterm', 'market_data_charts'):
        assert cfg['personas'][aid] == 'high'
    for aid in ('zh_macro', 'zh_industry', 'en_industry'):
        assert cfg['personas'][aid] == 'mid'
    for aid in ('en_macro', 'investing_philosophy', 'single_stock_deepdive_en', 'en_morris_archive'):
        assert cfg['personas'][aid] == 'low'


def test_high_tier_targets_four_and_retries():
    pol = ec.tier_policy('trading_shortterm')
    assert pol['tier'] == 'high' and pol['emotion_retry'] is True and pol['soft_findings'] is True
    brief = ec.build_emotion_brief(
        [{'unit_id': '1', 'statement': 'VIX crash panic dump liquidations', 'source_spans': [], 'numbers': []}],
        {'account_view': 'Vol looks cheap but overhang remains.'},
        lang='en', account_id='trading_shortterm')
    assert brief['target_intensity'] >= 4 and brief['emotion_retry'] is True
    assert brief['tier'] == 'high'


def test_mid_soft_findings_without_force_retry():
    pol = ec.tier_policy('zh_macro')
    assert pol['emotion_retry'] is False and pol['soft_findings'] is True
    brief = ec.build_emotion_brief(
        [{'unit_id': '1', 'statement': 'PMI 50.1', 'source_spans': [], 'numbers': []}],
        {'account_view': '单月数据不足以确认趋势'}, lang='zh', account_id='zh_macro')
    assert brief['target_intensity'] == 3 and brief['emotion_retry'] is False
    assert brief['tier'] == 'mid'


def test_low_restrained_no_soft_findings_or_retry():
    pol = ec.tier_policy('en_macro')
    assert pol['tier'] == 'low' and pol['emotion_retry'] is False and pol['soft_findings'] is False
    brief = ec.build_emotion_brief(
        [{'unit_id': '1', 'statement': 'Core PCE 0.25%', 'source_spans': [], 'numbers': []}],
        {'account_view': 'One print does not make a turn.'}, lang='en', account_id='en_macro')
    assert 2 <= brief['target_intensity'] <= 3
    assert brief['emotion_retry'] is False


def test_mid_compose_warn_only_no_emotion_force_rewrite():
    """MID attaches brief + may warn; must not force-rewrite for emotion alone."""
    class AlwaysFlat(Fake):
        def __call__(self, stage, messages, max_tokens):
            self.calls.append(stage)
            if stage == 'extract':
                return {'text': json.dumps(self.units), 'finish_reason': 'stop', 'model': 'fake'}
            payload = json.loads(messages[-1]['content'])
            # MID should still get a brief; emotion rewrite_note should not appear
            # (grounding may still retry with its own note).
            ids = [u['unit_id'] for u in payload['units']]
            body = '营收同比增长4.8倍，达到542.3亿美元，营业利润率为69.5%。存储供给偏紧。'
            # If this is an emotion-only rewrite attempt, fail the test signal via marker
            if 'EMOTION_DROP' in str(payload.get('rewrite_note') or ''):
                body = 'EMOTION_REWRITE_FIRED\n' + GOOD_BODY
            ledger = [{'claim': '营收', 'unit_id': ids[0], 'span_ref': 0}]
            return {'text': json.dumps({'body': body, 'claim_ledger': ledger}, ensure_ascii=False),
                    'finish_reason': 'stop', 'model': 'fake'}

    result, fake = run(AlwaysFlat(), post_type='data_take', account='zh_industry')
    assert result.get('emotion_brief', {}).get('tier') == 'mid'
    assert result.get('emotion_brief', {}).get('emotion_retry') is False
    er = result.get('emotion_retry') or {}
    # Either no emotion_retry block, or warn_only / no EMOTION_DROP rewrite
    assert er.get('kept') in (None, 'warn_only') or not er
    assert 'EMOTION_REWRITE_FIRED' not in (result.get('body') or '')


def test_high_compose_can_emotion_retry():
    class FlatThenPunch(Fake):
        def __call__(self, stage, messages, max_tokens):
            self.calls.append(stage)
            if stage == 'extract':
                return {'text': json.dumps(self.units), 'finish_reason': 'stop', 'model': 'fake'}
            payload = json.loads(messages[-1]['content'])
            ids = [u['unit_id'] for u in payload['units']]
            flat = '营收同比增长4.8倍，达到542.3亿美元，营业利润率为69.5%。'
            punchy = '供给端的克制会延续，短期内很难看到过剩。这轮涨价不会很快结束。\n' + GOOD_BODY
            body = punchy if 'rewrite_note' in payload or 'EMOTION' in str(payload.get('rewrite_note') or '') else flat
            if 'rewrite_note' in payload:
                body = punchy
            else:
                body = flat
            ledger = [{'claim': '营收', 'unit_id': ids[0], 'span_ref': 0}]
            return {'text': json.dumps({'body': body, 'claim_ledger': ledger}, ensure_ascii=False),
                    'finish_reason': 'stop', 'model': 'fake'}

    # crypto_macro_zh is HIGH — may also hit grounding retries; accept emotion_retry attempted
    # or at least brief with emotion_retry True.
    # zh SOURCE may not suit crypto account; use zh_industry path? Need HIGH account with ZH units.
    # market_data_charts / trading may be EN. Use crypto_macro_zh if compose accepts it with SOURCE.
    result, fake = run(FlatThenPunch(), post_type='data_take', account='crypto_macro_zh')
    brief = result.get('emotion_brief') or {}
    assert brief.get('tier') == 'high' and brief.get('emotion_retry') is True
    # Soft path only
    assert result['draft_status'] == 'draft_ready'
