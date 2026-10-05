"""Cross-language (ZH<->EN) subject matching for continues_view_id / related() (2026-10-06).

Oct 5 sim: a zh persona whose earlier view subject was Chinese got `fresh` (not `continue`) when the
new unit/stance subject was English - ZH bigrams and EN stems share no tokens. The bilingual alias
layer (live/finance_aliases.py) folds high-frequency subjects into language-neutral concepts before
overlap; thresholds are unchanged."""
import pytest

from live import finance_aliases, view_ledger
from live.view_ledger import CONTINUE_SUBJECT_MIN, CONTINUE_TEXT_MIN, continue_score


def call(subject, direction='lower', account_view='', decision='adapt', horizon='months'):
    return {'decision': decision, 'account_view': account_view or subject, 'confidence': 0.7,
            'view': {'subject': subject, 'direction': direction, 'conviction': 'medium', 'horizon': horizon}}


def score(a, b, av_a='', av_b=''):
    return continue_score({'subject': a}, av_a, {'subject': b, 'account_view': av_b})


def test_thresholds_unchanged():
    assert (CONTINUE_SUBJECT_MIN, CONTINUE_TEXT_MIN) == (0.4, 0.3)


@pytest.mark.parametrize('zh,en', [('美联储降息路径', 'Fed rate cut path'),
                                   ('制造业PMI', 'manufacturing PMI'),
                                   ('美债收益率', 'Treasury yields'),
                                   ('比特币ETF资金流', 'Bitcoin ETF flows'),
                                   ('通胀预期', 'inflation expectations'),
                                   ('非农就业', 'nonfarm payrolls employment'),
                                   ('VIX波动率', 'VIX volatility')])
def test_cross_language_peers_score_like_same_language(zh, en):
    s1, _ = score(zh, en)
    s2, _ = score(en, zh)
    assert s1 >= CONTINUE_SUBJECT_MIN and s2 >= CONTINUE_SUBJECT_MIN, (zh, en, s1, s2)


@pytest.mark.parametrize('a,b', [('美联储降息路径', 'Bitcoin ETF flows'),
                                 ('制造业PMI', 'Gold central bank buying'),
                                 ('比特币', 'memory supply'),
                                 ('Fed rate cut path', '存储供给偏紧'),
                                 ('原油供给', 'Treasury yields'),
                                 ('人民币汇率', 'Nasdaq earnings')])
def test_unrelated_pairs_stay_low(a, b):
    s, t = score(a, b, a, b)
    assert s <= 0.05 and t <= 0.05, (a, b, s, t)


def test_zh_prior_continues_from_en_call(tmp_path):
    led = view_ledger.ViewLedger('zh_macro', tmp_path)
    prior = led.record(call('美联储降息路径', account_view='美联储降息路径会比市场预期更慢。'), unit_ids=[], source_ids=[])
    led.record(call('比特币', direction='bearish', account_view='比特币短期偏弱。'), unit_ids=[], source_ids=[])
    new = call('Fed rate cut path', account_view='The Fed rate cut path stays slower than priced.')
    rows = led.related('Fed rate cut path The Fed rate cut path stays slower than priced.', k=5)
    assert rows and rows[0]['id'] == prior['id']
    out = led.link_continuity(new)
    assert out['continues_view_id'] == prior['id'] and out['continuity']['link'] == 'continue'
    assert out['continuity']['subject_overlap'] >= CONTINUE_SUBJECT_MIN


def test_en_prior_continues_from_zh_call(tmp_path):
    led = view_ledger.ViewLedger('zh_macro', tmp_path)
    prior = led.record(call('Fed rate cut path', account_view='Fed cuts come slower than priced.'), unit_ids=[], source_ids=[])
    out = led.link_continuity(call('美联储降息路径', account_view='美联储降息节奏偏慢。'))
    assert out['continues_view_id'] == prior['id']


def test_cross_language_flip_is_still_a_flip(tmp_path):
    led = view_ledger.ViewLedger('zh_macro', tmp_path)
    prior = led.record(call('美联储降息路径', direction='lower'), unit_ids=[], source_ids=[])
    out = led.link_continuity(call('Fed rate cut path', direction='higher'))
    assert out['continues_view_id'] is None
    assert out['continuity'].get('unacknowledged_flip_of') == prior['id']
    assert [f['code'] for f in led.contradictions(out)] == ['contradicts_prior_view']


def test_cross_language_unrelated_stays_fresh(tmp_path):
    led = view_ledger.ViewLedger('zh_macro', tmp_path)
    led.record(call('美联储降息路径', account_view='美联储降息路径偏慢。'), unit_ids=[], source_ids=[])
    out = led.link_continuity(call('Bitcoin ETF flows', account_view='Bitcoin ETF flows keep fading.'))
    assert out['continues_view_id'] is None and out['continuity']['link'] == 'fresh'


def test_zh_zh_pmi_still_links(tmp_path):
    led = view_ledger.ViewLedger('zh_macro', tmp_path)
    prior = led.record(call('制造业PMI景气回升', direction='higher',
                            account_view='制造业PMI回到荣枯线上方，景气在回升。'), unit_ids=[], source_ids=[])
    out = led.link_continuity(call('制造业PMI景气', direction='higher',
                                   account_view='制造业PMI连续第二个月在荣枯线上方，延续此前的观察。'))
    assert out['continues_view_id'] == prior['id']


def test_aliases_respect_word_boundaries_and_entities():
    c, _ = finance_aliases.canonicalize('FedEx shares and Ethernet chips')
    assert '@fed' not in c and '@eth' not in c
    assert finance_aliases.canonicalize('美联储')[0] == {'@fed'}
    assert '@ecb' in finance_aliases.canonicalize('欧洲央行')[0] and '@fed' not in finance_aliases.canonicalize('ECB')[0]
    # residual ZH text keeps bigrams but never straddles an alias span
    toks = view_ledger._tokens('通胀和美联储独立性')
    assert {'@inflation', '@fed', '独立', '立性'} <= toks and '储独' not in toks and '和独' not in toks
    assert finance_aliases.ALIAS_COUNT >= 200 and finance_aliases.CONCEPT_COUNT >= 50
