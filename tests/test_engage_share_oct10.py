"""Oct 10 (Fiona, engagement improvement #1): up to 2 of our accounts per target post if they differ in language or
mode; never two same-language replies, never twins; FD_ENGAGE_MAX_PER_POST=1 reverts. Fresh posts (<= 2h) get a
reply-first score boost; windows unchanged."""
from datetime import datetime, timedelta, timezone

from live import engagement

NOW = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)


def st(*users):
    s = engagement.DayState()
    for a, mode, lang in users:
        s.take(a, '111', 'big', mode, lang)
    return s


def test_open_for_rules(monkeypatch):
    monkeypatch.delenv('FD_ENGAGE_MAX_PER_POST', raising=False)
    assert st().open_for('111', 'a_en', 'en', 'reply')
    s = st(('crypto_macro_zh', 'reply', 'zh'))
    assert s.open_for('111', 'crypto_macro_en', 'en', 'quote')            # other language
    assert s.open_for('111', 'crypto_trader_en', 'en', 'reply')          # other language, reply ok
    assert s.open_for('111', 'crypto_onchain_zh', 'zh', 'quote')         # same language, other mode
    assert not s.open_for('111', 'crypto_onchain_zh', 'zh', 'reply')     # two zh replies
    assert not s.open_for('111', 'crypto_macro_zh', 'zh', 'quote')       # same account
    assert not st(('crypto_onchain_zh', 'quote', 'zh')).open_for('111', 'crypto_macro_zh', 'zh', 'quote')
    # mode=None: some allowed mode fits
    assert s.open_for('111', 'crypto_onchain_zh', 'zh', assess={'reply_ok': True, 'quote_ok': True})
    assert not s.open_for('111', 'crypto_onchain_zh', 'zh', assess={'reply_ok': True, 'quote_ok': False})
    # cap 2
    s2 = st(('crypto_macro_zh', 'reply', 'zh'), ('crypto_macro_en', 'quote', 'en'))
    assert not s2.open_for('111', 'crypto_trader_en', 'en', 'reply')
    monkeypatch.setenv('FD_ENGAGE_MAX_PER_POST', '1')
    assert not s.open_for('111', 'crypto_macro_en', 'en', 'quote')


def test_twins_never_share():
    for a, b in (('crypto_meme_zh', 'crypto_meme_en'), ('crypto_airdrop_zh', 'crypto_airdrop_en'),
                 ('crypto_prediction_zh', 'crypto_prediction_en'), ('crypto_stable_yield_en', 'crypto_stable_yield_zh')):
        lb = b.rsplit('_', 1)[1]
        assert not st((a, 'reply', a.rsplit('_', 1)[1])).open_for('111', b, lb, 'quote')


def src(age_h, lang='en', likes=800):
    return {'url': 'https://x.com/big/status/111', 'published_at': (NOW - timedelta(hours=age_h)).isoformat(),
            'source_language': lang, 'x_metrics': {'likes': likes, 'views': 200000, 'reposts': 50, 'replies': 40},
            'author_followers': 900000}


def test_fresh_boost(monkeypatch):
    a1 = engagement.assess(src(0.5), NOW, account_lang='en')
    a3 = engagement.assess(src(3), NOW, account_lang='en')
    monkeypatch.setenv('FD_ENGAGE_FRESH', '0')
    b1 = engagement.assess(src(0.5), NOW, account_lang='en')
    b3 = engagement.assess(src(3), NOW, account_lang='en')
    assert a1['score'] - b1['score'] > 0.7 and abs(a3['score'] - b3['score']) < 1e-9
    other_off = engagement.assess(src(0.5, lang='zh'), NOW, account_lang='en')
    monkeypatch.delenv('FD_ENGAGE_FRESH')
    other_on = engagement.assess(src(0.5, lang='zh'), NOW, account_lang='en')   # no reply possible: no boost
    assert abs(other_on['score'] - other_off['score']) < 1e-9
    cfg = engagement.config()
    assert cfg['reply_max_age_h'] == 6 and cfg['quote_max_age_h'] == 12


def test_plan_day_shares_post_across_languages(monkeypatch):
    monkeypatch.delenv('FD_ENGAGE_MAX_PER_POST', raising=False)
    s = src(1)
    cands = {'crypto_macro_en': [{'key': 'k1', 'source': s, 'on_lane': True}],
             'crypto_macro_zh': [{'key': 'k1', 'source': s, 'on_lane': True}],
             'crypto_trader_en': [{'key': 'k1', 'source': s, 'on_lane': True}]}
    langs = {'crypto_macro_en': 'en', 'crypto_macro_zh': 'zh', 'crypto_trader_en': 'en'}
    out, log = engagement.plan_day(cands, day='2026-10-10', ref=NOW, langs=langs)
    modes = {a: d['k1']['mode'] for a, d in out.items()}
    assert sum(bool(m) for m in modes.values()) == 2, modes
    used = sorted((a[-2:], m) for a, m in modes.items() if m)
    assert used in ([('en', 'quote'), ('en', 'reply')], [('en', 'reply'), ('zh', 'quote')]), used
    two = {'crypto_macro_en': cands['crypto_macro_en'], 'crypto_macro_zh': cands['crypto_macro_zh']}
    out2, _ = engagement.plan_day(two, day='2026-10-10', ref=NOW, langs=langs)
    assert out2['crypto_macro_en']['k1']['mode'] == 'reply' and out2['crypto_macro_zh']['k1']['mode'] == 'quote'
    monkeypatch.setenv('FD_ENGAGE_MAX_PER_POST', '1')
    out, _ = engagement.plan_day(cands, day='2026-10-10', ref=NOW, langs=langs)
    assert sum(bool(d['k1']['mode']) for d in out.values()) == 1
