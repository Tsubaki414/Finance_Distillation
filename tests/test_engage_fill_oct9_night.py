"""Oct 9 night (slot-2 fill rate): per-language like floors, views standing in for likes, extended quote window for
clearly high-traffic posts, donor median likes ignoring posts without metrics, curated thin-lane watchlists, and the
compose pick gate (an engagement pick must be a live target; one of our accounts per target post)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from live import engagement as E

BJT = E.BJT
DAY = '2026-10-10'
SLOT0 = datetime(2026, 10, 10, 8, 0, tzinfo=BJT)


def src(handle, pid, hours_before=2.0, likes=40, views=12000, followers=120000, lang='zh'):
    pub = SLOT0 - timedelta(hours=hours_before)
    return {'url': f'https://x.com/{handle}/status/{pid}', 'published_at': pub.isoformat(), 'source_language': lang,
            'x_metrics': {'likes': likes, 'views': views, 'followers': followers, 'reposts': 2, 'replies': 3}}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv('FD_ENGAGE', '1')
    monkeypatch.setenv('FD_SLOT_RULE', '1')
    monkeypatch.setenv('FD_ENGAGE_LOG', str(tmp_path / 'log'))
    monkeypatch.setattr(E, '_ROSTER', {})


def cfg(**kw):
    return {**E.DEFAULTS, **kw}


def test_zh_like_floor_is_lower_than_en():
    c = cfg()
    assert E.assess(src('qinba', '1', likes=40, views=5000), SLOT0, account_lang='zh', cfg=c)['quote_ok']
    assert E.assess(src('qinba', '1', likes=20, views=5000), SLOT0, account_lang='zh', cfg=c)['reject'] == 'low_engagement'
    en = E.assess(src('ted', '2', likes=40, views=5000, lang='en'), SLOT0, account_lang='en', cfg=c)
    assert en['reject'] == 'low_engagement'


def test_views_stand_in_for_likes():
    c = cfg()
    assert E.assess(src('zh1', '3', likes=12, views=15000), SLOT0, account_lang='zh', cfg=c)['quote_ok']
    assert E.assess(src('en1', '4', likes=60, views=45000, lang='en'), SLOT0, account_lang='en', cfg=c)['quote_ok']
    assert not E.assess(src('en1', '4', likes=60, views=20000, lang='en'), SLOT0, account_lang='en', cfg=c)['quote_ok']


def test_extended_quote_window_only_for_high_traffic_and_never_reply():
    c = cfg()
    hot = E.assess(src('ted', '5', hours_before=15, likes=900, views=60000, lang='en'), SLOT0, account_lang='en', cfg=c)
    assert hot['quote_ok'] and hot['extended'] and not hot['reply_ok']
    meh = E.assess(src('ted', '6', hours_before=15, likes=150, views=20000, lang='en'), SLOT0, account_lang='en', cfg=c)
    assert meh['reject'] == 'too_old'
    old = E.assess(src('ted', '7', hours_before=19, likes=5000, views=900000, lang='en'), SLOT0, account_lang='en', cfg=c)
    assert old['reject'] == 'too_old'
    assert E.max_age_h(hot, 'quote', c) == 18 and E.max_age_h(meh, 'quote', c) == 12 and E.max_age_h(hot, 'reply', c) == 6


def test_plan_day_uses_extended_window_for_slot_limit():
    cands = {'a': [{'key': 'k', 'source': src('ted', '8', hours_before=14, likes=900, views=80000, lang='en')}]}
    dec, log = E.plan_day(cands, day=DAY, ref=SLOT0 - timedelta(hours=1), langs={'a': 'en'})
    assert dec['a']['k']['mode'] == 'quote' and log


def test_donor_traffic_skips_posts_without_metrics(tmp_path):
    rows = [{'likes': n} for n in (260, 337, 5017, 1429, 563, 400)] + [{'likes': 0}] * 40
    (tmp_path / 'big.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    (tmp_path / 'nometrics.jsonl').write_text('\n'.join(json.dumps({'likes': 0}) for _ in range(20)))
    t = E.donor_traffic(tmp_path)
    assert t['big'] == pytest.approx(481.5) and 'nometrics' not in t


def test_watchlist_extra_adds_curated_handles(monkeypatch, tmp_path):
    roster = {'donors': {
        'a1': {'handle': 'cl1', 'persona_cluster': 'zh_industry', 'lang': 'zh', 'followers': 90000},
        'x1': {'handle': 'curated', 'persona_cluster': 'other', 'lang': 'zh', 'followers': 40000},
        'x2': {'handle': 'wronglang', 'persona_cluster': 'other', 'lang': 'en', 'followers': 40000},
        'x3': {'handle': 'stale', 'persona_cluster': 'other', 'lang': 'zh', 'followers': 40000, 'latest_post': '2026-08-01'}}}
    p = tmp_path / 'roster.json'
    p.write_text(json.dumps(roster))
    monkeypatch.setattr(E, 'ROSTER', p)
    acct = [{'id': 'zh_industry', 'lang': 'zh', 'retrieval_beats': []}]
    c = cfg(watchlist_extra={'zh_industry': ['curated', 'wronglang', 'stale', 'cl1']})
    rows = E.subscriptions(acct, cfg=c, traffic={})
    assert sorted(r['handle'] for r in rows) == ['cl1', 'curated']
    assert all(r['lang'] == 'zh' and r['engage'] for r in rows)


def test_live_config_curates_thin_lanes():
    extra = E.config().get('watchlist_extra') or {}
    for aid in ('zh_industry', 'zh_us_stocks', 'zh_longterm_investing', 'single_stock_deepdive_en', 'zh_macro'):
        assert len(extra.get(aid) or []) >= 3


def test_dashboard_card_shows_target_snippet():
    import importlib.util
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'scripts'))
    spec = importlib.util.spec_from_file_location('bod', root / 'scripts' / 'build_ops_dashboard.py')
    bod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bod)
    row = {'post_mode': 'reply', 'engagement': {'mode': 'reply', 'url': 'https://x.com/a/status/1', 'author': 'a'},
           'source': {'title': '$ETH tapped the $2,400 level before bounceback. ' * 5}}
    m = bod.media_of(row)
    assert m['target'] == 'https://x.com/a/status/1' and m['target_author'] == 'a'
    assert m['target_text'].startswith('$ETH tapped') and len(m['target_text']) <= 140
    assert bod.media_of({'post_mode': 'original'})['target_text'] == ''


def test_engagement_drafts_get_a_short_length_band():
    import importlib.util
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'scripts'))
    spec = importlib.util.spec_from_file_location('dc', root / 'scripts' / 'daily_compose.py')
    dc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dc)
    assert dc.ENGAGE_MAX_LEN['quote']['en'] <= 320 and dc.ENGAGE_MAX_LEN['reply']['zh'] <= 90
