"""live/engagement.py (FD_ENGAGE): big-account / velocity target scoring, cold-start reply + quote mix, timing,
safety checks, targets log, discovery subscriptions, and the wiring into post_mode / cold_start / daily_compose /
x_daily / content_store / qa_levels (Fiona, Oct 8: ride big accounts' traffic, not 8-like posts)."""
import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from live import cold_start, engagement as E, post_mode, qa_levels

ROOT = Path(__file__).resolve().parents[1]
BJT = E.BJT
DAY = '2026-10-09'
REF = datetime(2026, 10, 8, 22, 13, tzinfo=timezone.utc)          # 06:13 Beijing on 10-09 (the cron run)
SLOT0 = datetime(2026, 10, 9, 8, 0, tzinfo=BJT)                   # first slot of the day


def _script(name):
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def src(handle='bigacct', pid='1', hours_before=2.0, likes=150, views=20000, followers=120000, lang='zh',
        at=None, reposts=5, replies=10):
    pub = (at or SLOT0) - timedelta(hours=hours_before)
    m = {k: v for k, v in (('likes', likes), ('views', views), ('followers', followers), ('reposts', reposts),
                           ('replies', replies)) if v is not None}
    return {'url': f'https://x.com/{handle}/status/{pid}', 'published_at': pub.isoformat(), 'source_language': lang,
            'x_metrics': m}


@pytest.fixture(autouse=True)
def engage_on(monkeypatch, tmp_path):
    monkeypatch.setenv('FD_ENGAGE', '1')
    monkeypatch.setenv('FD_SLOT_RULE', '0')   # Oct 8 mix (cold accounts 1 reply + 1 quote); slot rule: test_slot_rule_oct9
    monkeypatch.setenv('FD_ENGAGE_LOG', str(tmp_path / 'engage_log'))
    monkeypatch.setenv('FD_COMPOSE_INBOX', str(tmp_path / 'inbox'))
    monkeypatch.setattr(E, '_ROSTER', {'hugeacct': 900000})


# ------------------------------------------------------------------ 1. target scoring

def test_big_author_with_engagement_is_a_reply_and_quote_target():
    a = E.assess(src(), SLOT0, account_lang='zh')
    assert a['quote_ok'] and a['reply_ok'] and a['reject'] is None and a['big']
    assert '@bigacct' in a['why'] and 'big author' in a['why']


def test_the_oct8_targets_are_refused():
    """@lianyanshe 8 likes / 4.0k views, 82.6k followers, ~22.5h old at the 22:29 slot; @off_thetarget 9 likes, 39k."""
    lian = src('lianyanshe', '2107862971024351373', hours_before=22.5, likes=8, views=4003, followers=82566)
    assert E.assess(lian, SLOT0)['reject'] == 'too_old'
    fresh = src('lianyanshe', '2', hours_before=2, likes=8, views=4003, followers=82566)
    assert E.assess(fresh, SLOT0)['reject'] == 'low_engagement'
    small = src('off_thetarget', '3', hours_before=2, likes=9, views=1271, followers=39033)
    assert E.assess(small, SLOT0)['reject'] == 'small_author'


def test_huge_author_waives_the_like_floor_and_velocity_waives_the_follower_floor():
    assert E.assess(src(likes=20, followers=450000), SLOT0)['quote_ok']
    hot = src('smallbutfast', hours_before=1.0, likes=120, views=30000, followers=4000)
    a = E.assess(hot, SLOT0)
    assert a['hot'] and a['quote_ok'] and 'velocity' in a['why']
    slow = src('smallslow', hours_before=5.0, likes=120, views=3000, followers=4000)
    assert E.assess(slow, SLOT0)['reject'] == 'small_author'


def test_age_windows_are_measured_at_the_post_time():
    s = src(hours_before=8)
    a = E.assess(s, SLOT0)
    assert a['quote_ok'] and not a['reply_ok']                         # 6h reply window, 12h quote window
    assert E.assess(s, SLOT0 + timedelta(hours=5))['reject'] == 'too_old'
    assert E.assess(src(hours_before=-1), SLOT0)['reject'] == 'not_yet_posted'


def test_missing_metrics_own_handle_other_language_and_non_x():
    assert E.assess(src(likes=None, views=None, followers=None), SLOT0)['reject'] == 'no_metrics'
    assert E.assess(src('hugeacct', likes=None, views=None, followers=None), SLOT0)['quote_ok']   # roster: huge
    assert E.assess(src(), SLOT0, own_handles=['@BigAcct'])['reject'] == 'own_account'
    other = E.assess(src(lang='en'), SLOT0, account_lang='zh')
    same = E.assess(src(lang='zh'), SLOT0, account_lang='zh')
    assert other['quote_ok'] and not other['reply_ok'] and other['score'] < same['score']
    assert E.assess({'url': 'https://www.coindesk.com/a', 'published_at': SLOT0.isoformat()}, SLOT0)['reject'] == 'not_x'


def test_score_prefers_more_traffic_and_fresher_posts():
    hi = E.assess(src(likes=900, views=200000, followers=400000), SLOT0)['score']
    lo = E.assess(src(likes=120, views=9000, followers=60000), SLOT0)['score']
    old = E.assess(src(likes=900, views=200000, followers=400000, hours_before=10), SLOT0)['score']
    assert hi > lo and hi > old


# ------------------------------------------------------------------ 2. timing

def test_next_slot_window_gap_and_age_limit():
    assert E.next_slot(DAY, REF) == SLOT0                                   # 06:13 run -> 08:00 Beijing
    assert E.next_slot(DAY, REF, taken=[SLOT0]) == SLOT0 + timedelta(minutes=30)
    late = datetime(2026, 10, 9, 22, 50, tzinfo=BJT)
    assert E.next_slot(DAY, late) is None                                    # past 22:59 with the lead
    assert E.next_slot(DAY, REF, taken=[SLOT0], not_after=SLOT0 + timedelta(minutes=10)) is None
    noon = datetime(2026, 10, 9, 12, 0, tzinfo=BJT)
    assert E.next_slot(DAY, noon) == noon + timedelta(minutes=10)


# ------------------------------------------------------------------ 3. mode mix + exclusivity

def _plan(cands, state=None, cold=True, taken=None):
    return E.plan_day(cands, day=DAY, ref=REF, state=state, taken=taken, langs={a: 'zh' for a in cands},
                      cold={a: cold for a in cands})


def test_one_reply_and_one_quote_per_day_rest_standalone():
    cands = {'a': [{'key': 'k1', 'source': src('big1', '11', hours_before=1, likes=400)},
                   {'key': 'k2', 'source': src('big2', '12', hours_before=9, likes=800)},
                   {'key': 'k3', 'source': src('big3', '13', hours_before=4, likes=110, views=3000)}]}
    dec, log = _plan(cands)
    modes = {k: d['mode'] for k, d in dec['a'].items()}
    assert sorted(m for m in modes.values() if m) == ['quote', 'reply']
    assert modes['k2'] == 'quote'                              # 9h old: quote only
    slots = sorted(d['slot'] for d in dec['a'].values() if d['mode'])
    assert slots[0] == SLOT0 and slots[1] - slots[0] >= timedelta(minutes=30)
    assert {e['mode'] for e in log} == {'quote', 'reply'} and all(e['author_followers'] for e in log)


def test_two_replies_when_no_quote_target_is_left_and_fallback_when_none():
    cands = {'a': [{'key': 'k1', 'source': src('big1', '21', hours_before=1)},
                   {'key': 'k2', 'source': src('big2', '22', hours_before=2)}]}
    dec, _ = _plan(cands, state=_used('a', quote=1))
    assert [d['mode'] for d in dec['a'].values()] == ['reply', 'reply']
    none, log = _plan({'a': [{'key': 'k', 'source': src(likes=5, followers=2000)}]})
    assert none['a']['k']['mode'] is None and log == []


def _used(account, quote=0, reply=0):
    st = E.DayState()
    st.used[account] = {'quote': quote, 'reply': reply}
    return st


def test_no_two_accounts_on_one_target_and_one_hit_per_author_per_account():
    shared = src('big1', '31', hours_before=1, likes=500)
    cands = {'a': [{'key': 'x', 'source': shared}], 'b': [{'key': 'x', 'source': shared}]}
    dec, log = _plan(cands)
    takers = [a for a in ('a', 'b') if dec[a]['x']['mode']]
    assert len(takers) == 1 and log[0]['passed_over'] == [({'a', 'b'} - set(takers)).pop()]
    same_author = {'a': [{'key': 'p1', 'source': src('big1', '41', hours_before=1)},
                         {'key': 'p2', 'source': src('big1', '42', hours_before=2)}]}
    dec2, _ = _plan(same_author)
    assert sum(bool(d['mode']) for d in dec2['a'].values()) == 1


def test_earlier_rows_of_the_day_count_and_warm_accounts_get_no_mode():
    rows = [{'account_id': 'a', 'post_mode': 'reply', 'reply_to_url': 'https://x.com/big1/status/51'},
            {'account_id': 'b', 'engagement': {'mode': 'quote', 'url': 'https://x.com/big9/status/52'}}]
    st = E.DayState.from_rows(rows)
    cands = {'a': [{'key': 'k', 'source': src('big1', '53', hours_before=1)}],
             'c': [{'key': 'k', 'source': src('big9', '52', hours_before=1)}]}
    dec, _ = _plan(cands, state=st)
    assert dec['a']['k']['mode'] is None                      # same author already replied to today by account a
    assert dec['c']['k']['mode'] is None                      # target post already taken by account b
    warm, _ = _plan({'a': [{'key': 'k', 'source': src()}]}, cold=False)
    assert warm['a']['k']['mode'] is None


def test_cold_window_is_thirty_days_from_first_day():
    assert E.is_cold('crypto_macro_zh', '2026-11-06')            # default first day 10-08
    assert not E.is_cold('crypto_macro_zh', '2026-11-07')
    # fd6af27 gave accounts 27-35 a first day (10-09); #36 crypto_stable_yield_en has none yet (null = cold)
    assert E.is_cold('crypto_meme_zh', '2026-11-07') and not E.is_cold('crypto_meme_zh', '2026-11-08')
    assert E.is_cold('crypto_stable_yield_en', '2027-01-01')     # not started yet = cold


# ------------------------------------------------------------------ 4. draft checks + prompt

def test_engagement_findings():
    codes = lambda body, mode='reply', lang='zh': {f['code'] for f in E.findings(body, mode, lang)}  # noqa: E731
    assert codes('说得好，学到了') >= {'engage_generic', 'engage_no_payload'}
    assert codes('Great post. Funding flipped to -0.02%.', lang='en') == {'engage_generic'}
    assert 'engage_too_long' in codes('第一句有 5.3%。第二句。第三句也有。')
    assert codes('@a @b 收益率 5.3% 了') == {'engage_mentions'}
    assert codes('拍卖认购倍数 2.77 倍，比前六次均值 2.54 高一截') == set()
    assert codes('不过融资窗口一紧，这条线就不是底了') == set()                 # counter-point, no number
    assert E.findings('说得好', None, 'zh') == []                             # not an engagement draft
    assert qa_levels.level({'code': 'engage_generic'}, frame_found=False) == 'hard' and \
        qa_levels.level({'code': 'engage_no_payload'}, frame_found=False) == 'soft'
    assert 'engage_no_payload' in qa_levels.FIXES


def test_prompt_rule_names_the_author_and_the_limits():
    r = E.prompt_rule('reply', 'PhyrexNi')
    assert '@PhyrexNi' in r and '2 sentences' in r and 'number' in r
    assert 'one @mention' in E.prompt_rule('quote', None)


# ------------------------------------------------------------------ 5. wiring: post_mode / cold_start / pick_prefs

def _row(mode, reject=None):
    return {'id': 'r1', 'day': DAY, 'account_id': 'crypto_macro_zh', 'post_format': {'type': 'quick_take'},
            'source': {'url': 'https://x.com/big1/status/61', 'published_at': (SLOT0 - timedelta(hours=1)).isoformat()},
            'engagement': {'mode': mode, 'why': 'w', 'reject': reject}}


def test_post_mode_follows_the_engagement_block(tmp_path):
    assert post_mode.decide(_row('reply'), tmp_path)['reply_to_url'] == 'https://x.com/big1/status/61'
    assert post_mode.decide(_row('quote'), tmp_path)['quote_target_url'] == 'https://x.com/big1/status/61'
    d = post_mode.decide(dict(_row(None, 'low_engagement'), post_format={'type': 'quote_comment'}), tmp_path)
    assert d['post_mode'] == 'original' and 'low_engagement' in d['post_mode_why']
    assert post_mode.decide(_row('quote'), tmp_path, env={'FD_ENGAGE': '0'})['post_mode'] == 'original'


def test_cold_start_defers_to_engagement_and_window_is_12h(monkeypatch):
    s = {'url': 'https://x.com/d/status/1', 'published_at': (REF - timedelta(hours=2)).isoformat()}
    assert not any(cold_start.force_quote('crypto_meme_en', date(2026, 10, 9), s, REF, key=f'k{i}') for i in range(50))
    assert not cold_start.hot_quote_target(dict(s, published_at=(REF - timedelta(hours=13)).isoformat()), REF)
    row = {'id': 'x', 'account_id': 'crypto_meme_en', 'day': DAY, 'source': s, 'suggested_post_time_london': REF.isoformat()}
    assert post_mode._cold_hot(row, s) == 0.0


def test_pick_prefs_ranks_scored_targets_first(monkeypatch):
    dc = _script('daily_compose')
    monkeypatch.setattr(cold_start, '_PROFILES', {})

    def g(source):
        return [{'source': dict(source, title='t'), 'unit': {'statement': 't', 'numbers': []}}]
    target = g(src('big1', '71', hours_before=1, at=SLOT0))
    unscored = g({'url': 'https://x.com/d/status/72', 'published_at': (REF - timedelta(hours=1)).isoformat()})
    news = g({'url': 'https://www.coindesk.com/a', 'published_at': REF.isoformat()})
    small = g(src('tiny', '73', hours_before=1, likes=3, followers=900, at=SLOT0))
    k = dc.pick_prefs('crypto_macro_zh', date(2026, 10, 9), REF, account_lang='zh')
    assert k(target)[0][0] == 0 and k(unscored)[0] == (1, 0.0) and k(news)[0] == (2, 0.0) and k(small)[0] == (2, 0.0)
    assert k(target) < k(unscored) < k(news)


def test_engagement_plan_in_daily_compose_marks_picks_and_logs(monkeypatch, tmp_path):
    dc = _script('daily_compose')

    def pick(sid, s):
        return {'source_id': sid, 'url': s['url'], 'published_at': s['published_at'], 'x_metrics': s['x_metrics'],
                'source_lang': 'zh'}
    plan = {'crypto_macro_zh': [pick('s1', src('big1', '81', hours_before=1, likes=400)),
                                pick('s2', src('tiny', '82', hours_before=1, likes=4, followers=800))],
            'crypto_onchain_zh': [pick('s3', src('big1', '81', hours_before=1, likes=400))]}
    accounts = [{'id': 'crypto_macro_zh', 'lang': 'zh'}, {'id': 'crypto_onchain_zh', 'lang': 'zh'}]
    info = {}
    dec = dc.engagement_plan(plan, accounts, {}, date(2026, 10, 9), REF, REF, (), info)
    modes = {(a, k): d['mode'] for a, ds in dec.items() for k, d in ds.items()}
    assert sum(bool(m) for m in modes.values()) == 1 and modes[('crypto_macro_zh', 's2')] is None
    t = info['engagement']['targets'][0]
    assert t['author'] == 'big1' and t['likes_at_selection'] == 400 and len(t['passed_over']) == 1
    E.write_log(DAY, info['engagement']['targets'], run_id='r1')
    E.write_log(DAY, info['engagement']['targets'], run_id='r2')
    assert len(E.read_log(DAY)['targets']) == 1 and E.read_log(DAY)['targets'][0]['run_id'] == 'r2'


def test_inbox_row_carries_the_engagement_block():
    dc = _script('daily_compose')
    pick = {'source_id': 's', 'post_format': {'type': 'one_liner', 'engage': 'reply'}, 'angle_why': '',
            'shared_event_with': [], 'suggested_post_time_london': SLOT0.isoformat(),
            'engagement': {'mode': 'reply', 'url': 'https://x.com/big1/status/9'}}
    row = dc.inbox_row({'plan': pick, 'body': 'x', 'text': 'x', 'status': 'ok'},
                       {'id': 'a', 'no': 1, 'name': 'n', 'beat': 'b', 'lang': 'zh'}, date(2026, 10, 9), 'run')
    assert row['engagement']['mode'] == 'reply'


# ------------------------------------------------------------------ 6. data: metrics kept, discovery, intake filter

def test_x_metrics_survive_into_the_store(tmp_path):
    from live import x_daily
    from live.content_store import ContentStore
    post = {'id': '91', 'text': 'BTC 资金费率翻负，空头在 8.2 万上方加仓', 'created': '2026-10-08T22:00:00+00:00',
            'likes': 300, 'views': 40000, 'reposts': 9, 'replies': 30, 'followers': 210000,
            'fetched_at': '2026-10-08T23:00:00+00:00'}
    s = x_daily.to_source(post, {'handle': 'big1', 'source_id': 'x_big1', 'accounts': ['crypto_macro_zh']})
    assert s['x_metrics'] == {'likes': 300, 'views': 40000, 'reposts': 9, 'replies': 30, 'followers': 210000,
                              'at': '2026-10-08T23:00:00+00:00'}
    db = ContentStore(tmp_path)
    unit = {'unit_id': 'cu-1', 'licence_tier': 'B', 'kind': 'fact', 'statement': 's', 'source_spans': []}
    db.add(s, [unit], adapter='x:big1')
    assert db.units()[0]['source']['x_metrics']['likes'] == 300


def test_normalise_reads_reposts_replies_and_followers():
    sys.path.insert(0, str(ROOT / 'scripts'))
    from scrape_donor_posts import normalise
    t = {'rest_id': '5', 'legacy': {'full_text': 'x', 'user_id_str': '1', 'favorite_count': 7, 'retweet_count': 2,
                                    'reply_count': 3, 'created_at': 'Thu Oct 08 01:00:00 +0000 2026'},
         'views': {'count': '99'}, 'core': {'user_results': {'result': {'legacy': {'followers_count': 123456}}}}}
    n = normalise(t)
    assert (n['likes'], n['views'], n['reposts'], n['replies'], n['followers']) == (7, 99, 2, 3, 123456)


def test_discovery_picks_big_same_language_donors():
    rows = E.subscriptions([{'id': 'crypto_macro_zh', 'lang': 'zh',
                             'retrieval_beats': ['crypto_macro_zh', 'crypto_macro_en', 'macro_zh']}])
    assert rows and len(rows) <= E.config()['targets_per_account']
    assert all(r['engage'] and r['tier'] == 'B' and r['accounts'] == ['crypto_macro_zh'] for r in rows)
    assert all((r['followers'] or 0) >= E.config()['min_followers'] for r in rows)
    roster = json.loads(E.ROSTER.read_text())['donors']
    assert all((roster.get(r['handle'].lower()) or {}).get('lang') == 'zh' for r in rows)
    assert E.subscriptions([{'id': 'crypto_macro_zh', 'lang': 'zh', 'retrieval_beats': ['crypto_macro_zh']}],
                           exclude={rows[0]['handle']})[0]['handle'] != rows[0]['handle']


def test_gather_fetches_engage_targets_and_drops_small_or_stale_posts():
    from live import x_daily
    now = datetime(2026, 10, 8, 23, 0, tzinfo=timezone.utc)

    texts = {'201': '伊朗局势升温，油价隔夜跳涨 4%，避险盘先去了美债短端', '202': '美联储会议纪要偏鹰，多数委员支持年内再加一次',
             '203': '某山寨币合约持仓一夜翻倍，资金费率冲到 0.1%', '204': '十年期美债拍卖认购倍数 2.77，比前六次均值高',
             '205': '美债10年期收益率 5.3%，比特币和黄金一起被抛，纳指还撑着'}

    def post(pid, hours, likes, followers=300000):
        return {'id': pid, 'created': (now - timedelta(hours=hours)).isoformat(), 'handle': 'bigtarget',
                'text': texts[pid], 'likes': likes, 'views': 50000, 'followers': followers}
    sub = {'handle': 'bigtarget', 'source_id': 'x_bigtarget', 'accounts': ['crypto_macro_zh'], 'roles': ['ENGAGE'],
           'tier': 'B', 'core': False, 'breadth': True, 'engage': True, 'beats': [[]]}
    got = {'bigtarget': [post('205', 1, 500), post('204', 2, 400), post('202', 3, 300), post('203', 2.5, 5, 60000),
                         post('201', 13, 900)]}
    calls = []
    res = x_daily.gather({}, now=now, subs=[sub], rapid=lambda h, u: [], apify=lambda h, s: ({}, {}),
                         breadth=lambda s: ({}, {}), engage=lambda s: (calls.append(s) or got, {'run_handles': ['bigtarget']}))
    ids = [s['id'] for s in res['selected']]
    assert calls and ids == ['x-205', 'x-204']                              # engage_posts_per_handle = 2
    assert res['filtered'].get('engage_low_engagement') == 1
    assert res['selected'][0]['x_metrics']['followers'] == 300000 and res['selected'][0]['x_metrics']['at']


def test_engage_off_switch(monkeypatch):
    monkeypatch.setenv('FD_ENGAGE', '0')
    assert not E.enabled() and not E.fetch_enabled() and E.findings('说得好', 'reply', 'zh') == []
    s = {'url': 'https://x.com/d/status/1', 'published_at': (REF - timedelta(hours=2)).isoformat()}
    assert sum(cold_start.force_quote('crypto_meme_en', date(2026, 10, 9), s, REF, key=f'k{i}') for i in range(100)) > 30


# ------------------------------------------------------------------ 7. dashboard: pinned slots, meta line, targets panel

def test_dashboard_pins_engagement_slots_and_shows_the_numbers(tmp_path):
    ob = _script('build_ops_dashboard')
    row = {'post_mode': 'reply', 'reply_to_url': 'https://x.com/PhyrexNi/status/1',
           'engagement': {'mode': 'reply', 'author': 'PhyrexNi', 'followers': 408002, 'likes': 43, 'views': 11368,
                          'age_h': 2.2}}
    m = ob.media_of(row)
    assert m['pinned'] and m['engage_meta'] == '@PhyrexNi · 40.8万粉 · 选中时 43赞 · 1.1万阅 · 发帖后 2.2h 发出'
    assert not ob.media_of({'post_mode': 'quote', 'quote_target_url': 'u'})['pinned']
    day = '2026-10-09'
    pin = '2026-10-09T11:10:00+08:00'
    drafts = [{'id': 'e', 'account_id': 'a', 'time': pin, 'pinned': True}] + [
        {'id': f'o{i}', 'account_id': 'a', 'time': f'2026-10-09T0{i + 1}:00:00+08:00'} for i in range(3)]
    out = ob.clamp_times(drafts, day)
    times = {d['id']: datetime.fromisoformat(d['time']) for d in out}
    assert times['e'] == datetime.fromisoformat(pin)
    ts = sorted(times.values())
    assert all(b - a >= timedelta(minutes=30) for a, b in zip(ts, ts[1:]))
    assert all(datetime(2026, 10, 9, 8, 0, tzinfo=BJT) <= t <= datetime(2026, 10, 9, 22, 59, tzinfo=BJT) for t in ts)
    (tmp_path / f'{day}.json').write_text(json.dumps({'targets': [{'account': 'a', 'mode': 'reply', 'author': 'x',
                                                                    'likes_at_selection': 184, 'secret': 1}]}))
    t = ob.load_targets(day, base=tmp_path)
    assert t[0]['likes_at_selection'] == 184 and 'secret' not in t[0] and ob.load_targets('2026-01-01', tmp_path) == []
