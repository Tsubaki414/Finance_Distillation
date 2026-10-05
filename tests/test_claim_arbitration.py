"""Cross-persona claim arbitration: same conclusion → one keeper, others soft HOLD."""
import json

from live import claim_arbitration as ca
from live import compose, qa_levels


def _cand(account_id, subject, direction, view, *, key=None, source_id='glassnode_research',
          source_lang='en', url='https://research.glassnode.com/pricing-out-the-hike', day='2026-10-02'):
    return {
        'key': key or f'{account_id}#1',
        'account_id': account_id,
        'subject': subject,
        'direction': direction,
        'account_view': view,
        'source_id': source_id,
        'source_lang': source_lang,
        'event_key': url,
        'unit_ids': ['cu-demo'],
        'day': day,
    }


BTC_SUBJ = 'Bitcoin price reaction to declining Fed hike odds'
BTC_EN = 'Bitcoin shrugging off declining Fed hike odds suggests macro repricing is not the driver right now.'
BTC_ZH = '比特币短期内对降息预期的钝感反应，说明当前价格驱动力不在货币政策预期。'
BTC_CHARTS = "Bitcoin's muted response to each drop in Fed hike odds — rate-sensitivity narratives aren't moving price."


def test_opposite_directions_may_disagree():
    a = _cand('crypto_macro_en', BTC_SUBJ, 'bullish', 'Bitcoin breaks higher on ETF inflows.')
    b = _cand('crypto_macro_zh', BTC_SUBJ, 'bearish', '比特币将继续承压，ETF流入撑不住。')
    assert ca.claims_collide(a, b) is False
    out = ca.arbitrate([a, b])
    assert [d['status'] for d in out] == [ca.WRITE, ca.WRITE]


def test_same_conclusion_keeps_specialty_owner():
    cands = [
        _cand('crypto_macro_zh', BTC_SUBJ, 'mixed', BTC_ZH, key='crypto_macro_zh#1'),
        _cand('market_data_charts', '', None, BTC_CHARTS, key='market_data_charts#2'),
        _cand('crypto_macro_en', BTC_SUBJ, 'neutral', BTC_EN, key='crypto_macro_en#1'),
    ]
    out = ca.arbitrate(cands)
    by = {d['key']: d for d in out}
    assert by['crypto_macro_en#1']['status'] == ca.WRITE
    assert by['crypto_macro_zh#1']['status'] == ca.HOLD
    assert by['market_data_charts#2']['status'] == ca.HOLD
    assert by['crypto_macro_zh#1']['reassigned_to'] == 'crypto_macro_en'
    assert by['crypto_macro_zh#1']['reason_code'] == ca.REASON_DUPLICATE
    assert by['crypto_macro_zh#1']['soft'] is True


def test_non_collision_control_stays_write():
    cands = [
        _cand('crypto_macro_en', BTC_SUBJ, 'neutral', BTC_EN),
        _cand('zh_macro', '中国制造业产出', 'bullish',
              'PMI刚回到荣枯线上方，单月数据不足以确认趋势。',
              key='zh_macro#1', source_id='stats_gov', source_lang='zh',
              url='https://www.stats.gov.cn/pmi'),
    ]
    out = ca.arbitrate(cands)
    assert [d['status'] for d in out] == [ca.WRITE, ca.WRITE]


def test_apply_to_results_soft_flags_without_deleting():
    drafts = [
        {'key': 'crypto_macro_en#1', 'account_id': 'crypto_macro_en', 'status': 'held',
         'text': 'body-en', 'stance': {'decision': 'adapt', 'account_view': BTC_EN,
                                       'view': {'subject': BTC_SUBJ, 'direction': 'neutral'}},
         'source': {'source_id': 'glassnode_research', 'lang': 'en',
                    'url': 'https://research.glassnode.com/pricing-out-the-hike'}},
        {'key': 'crypto_macro_zh#1', 'account_id': 'crypto_macro_zh', 'status': 'held',
         'text': 'body-zh', 'stance': {'decision': 'adapt', 'account_view': BTC_ZH,
                                       'view': {'subject': BTC_SUBJ, 'direction': 'mixed'}},
         'source': {'source_id': 'glassnode_research', 'lang': 'en',
                    'url': 'https://research.glassnode.com/pricing-out-the-hike'}},
        {'key': 'market_data_charts#2', 'account_id': 'market_data_charts', 'status': 'held',
         'text': 'body-charts', 'stance': {'decision': 'adapt', 'account_view': BTC_CHARTS,
                                           'view': {}},
         'source': {'source_id': 'glassnode_research', 'lang': 'en',
                    'url': 'https://research.glassnode.com/pricing-out-the-hike'}},
    ]
    out = compose.arbitrate_batch(drafts)
    assert all(r.get('text') for r in out)  # never deleted
    kept = [r for r in out if r['arbitration']['status'] == ca.WRITE]
    held = [r for r in out if r['arbitration']['status'] == ca.HOLD]
    assert len(kept) == 1 and kept[0]['account_id'] == 'crypto_macro_en'
    assert len(held) == 2
    for r in held:
        assert any(f['code'] == ca.REASON_CODE_SOFT for f in r['post_checks'])
        assert r['status'] == 'held'
    assert ca.REASON_CODE_SOFT in qa_levels.SOFT


def test_neutral_and_mixed_are_compatible_same_conclusion():
    assert ca.direction_compatible('neutral', 'mixed') is True
    assert ca.direction_compatible('bullish', 'bearish') is False
