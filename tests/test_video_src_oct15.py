"""Oct 15 FD_VIDEO_SRC: daily video-transcript idea source for two lifestyle / newbie ZH accounts (no network, no model)."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from live import attribution_frame, compose, registry, source_display, source_routes, video_src

ROOT = Path(__file__).resolve().parents[1]
RAW = json.loads((ROOT / 'tests/fixtures/video_src_user_tweets.json').read_text())
UNITS = json.loads((ROOT / 'tests/fixtures/video_src_units.json').read_text())
EMPTY = {'result': {'timeline': {'instructions': []}}}
NOW = datetime(2026, 10, 15, 22, 13, tzinfo=timezone.utc)
SRC = {'source_id': video_src.SOURCE_ID, 'original_text': '沟通的本质从某个角度来讲其实就是示弱，我们很多人不会示弱，遇到比你强的你还硬刚那能行吗。'}


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.delenv('FD_VIDEO_SRC', raising=False)
    monkeypatch.delenv('FD_VIDEO_ACCOUNTS', raising=False)
    source_routes._routes.cache_clear()
    yield
    source_routes._routes.cache_clear()


class FakeClient:
    def __init__(self, pages):
        self.pages, self.calls, self.made = list(pages), [], 0

    def get(self, path, **params):
        self.calls.append((path, params))
        self.made += 1
        return self.pages.pop(0)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


# ---------------------------------------------------------------- fetch / select

def test_own_video_ignores_quoted_video_and_reads_duration():
    vids = video_src.own_videos(RAW)
    assert vids['2110378342310428743'] == 252934          # the quote post's OWN video, not the quoted 765701 one
    assert 765701 not in vids.values()
    assert vids['2110353679316304381'] == 48506
    assert '2110348534579118184' not in vids


def test_throttle_keeps_under_30_calls_a_minute():
    clock = Clock()
    th = video_src.Throttle(clock=clock, sleep=clock.sleep)
    for _ in range(31):
        th.wait()
    assert clock.t >= 30 * video_src.CALL_GAP_S
    assert 60 / video_src.CALL_GAP_S <= 30


def test_fetch_posts_one_page_when_no_cursor_and_caps_pages():
    client = FakeClient([RAW])
    posts = video_src.fetch_posts(client, throttle=video_src.Throttle(gap_s=0), since=NOW - timedelta(days=30) + timedelta(days=29, hours=23))
    assert len(client.calls) == 1 and client.calls[0][1]['user'] == video_src.UID
    assert {p['id'] for p in posts if p['video_ms']} == {'2110691656081289325', '2110378342310428743', '2110353679316304381'}
    paged = dict(RAW, cursor={'bottom': 'abc'})
    client = FakeClient([paged] * 10)
    video_src.fetch_posts(client, throttle=video_src.Throttle(gap_s=0), since=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert len(client.calls) == video_src.MAX_PAGES


def test_select_top_liked_window_duration_and_caps():
    client = FakeClient([RAW])
    posts = video_src.fetch_posts(client, throttle=video_src.Throttle(gap_s=0), since=NOW - timedelta(hours=1))
    sel, skipped = video_src.select_videos(posts, now=NOW)
    assert [p['id'] for p in sel] == ['2110378342310428743', '2110353679316304381']   # by likes; 8-like post under MIN_LIKES
    assert skipped['few_likes'] == 1
    sel, skipped = video_src.select_videos(posts, now=NOW + timedelta(hours=40))        # both fall out of the 48 h window
    assert sel == [] and skipped['outside_window'] >= 2
    long = [dict(p, video_ms=16 * 60 * 1000) for p in posts if p['video_ms']]
    assert video_src.select_videos(long, now=NOW)[0] == []                                # 15 min cap
    many = [dict(posts[2], id=str(2110000000000000000 + i), likes=100 + i) for i in range(9)]
    sel, skipped = video_src.select_videos(many, now=NOW, max_videos=6)
    assert len(sel) == 6 and sel[0]['likes'] == 108 and skipped['over_daily_cap'] == 3
    sel, _ = video_src.select_videos(posts, now=NOW, seen={'video-2110378342310428743'}, failed={'2110353679316304381': 2})
    assert sel == []


def test_collect_skips_videos_that_do_not_fit_the_time_budget(tmp_path):
    clock = Clock()
    done = []

    def downloader(sid, d, timeout):
        clock.t += 30
        return Path(d) / f'{sid}.mp3'

    def transcriber(audio, out, timeout):
        clock.t += 100
        done.append(Path(audio).stem)
        return {'language': 'zh', 'segments': [{'start': 0, 'end': 1, 'text': '第一句话在这里，说的是每天固定投入半小时。'}] * 8}

    state = {}
    res = video_src.collect(state, now=NOW, out_dir=tmp_path, client=FakeClient([RAW, EMPTY]), budget_s=160, clock=clock,
                            downloader=downloader, transcriber=transcriber, throttle=video_src.Throttle(gap_s=0))
    assert res['status'] == 'ok' and res['selected'] == 2
    assert res['done'] == ['2110378342310428743']                 # 253 s audio needs ~108 s; the 48 s one no longer fits
    assert res['skipped']['time_budget'] == 1
    meta = json.loads((tmp_path / '20261015' / '2110378342310428743.json').read_text())
    assert meta['duration_s'] == 252.9 and (tmp_path / '20261015' / '2110378342310428743.txt').exists()
    # a failure is counted, never raised
    def boom(*a, **k):
        raise RuntimeError('yt-dlp blocked')
    res = video_src.collect({}, now=NOW, out_dir=tmp_path / 'b', client=FakeClient([RAW, EMPTY]), budget_s=900, downloader=boom,
                            throttle=video_src.Throttle(gap_s=0))
    assert res['status'] == 'ok' and len(res['failed']) == 2 and not res['done']


def test_collect_disabled_and_no_key(monkeypatch, tmp_path):
    monkeypatch.setenv('FD_VIDEO_SRC', '0')
    assert video_src.collect({}, now=NOW, out_dir=tmp_path)['status'] == 'disabled'
    monkeypatch.setenv('FD_VIDEO_SRC', '1')
    monkeypatch.delenv('RAPID_X_API_KEY', raising=False)
    assert video_src.collect({}, now=NOW, out_dir=tmp_path)['status'] == 'no_rapid_key'


def test_transcript_paragraphs_and_pending_sources(tmp_path):
    data = {'segments': [{'text': '每天固定投入半小时就好'}] * 30}
    text = video_src.transcript_text(data)
    assert text.count('\n\n') >= 1 and text.endswith('。')
    day = tmp_path / '20261015'
    day.mkdir()
    (day / '2110.txt').write_text(text)
    (day / '2110.json').write_text(json.dumps({'id': '2110', 'created': 'Wed Oct 14 12:23:00 +0000 2026', 'likes': 9,
                                               'duration_s': 5, 'transcript_file': '2110.txt'}))
    (day / '2110.whisper.json').write_text('{}')
    srcs = video_src.pending_sources(tmp_path, now=NOW)
    assert len(srcs) == 1 and srcs[0]['source_id'] == video_src.SOURCE_ID and srcs[0]['adapter'] == 'video_idea'
    assert srcs[0]['author_name'] == '' and srcs[0]['published_at'].startswith('2026-10-14T12:23')
    assert video_src.pending_sources(tmp_path, now=NOW, seen={'video-2110'}) == []


def test_clean_units_drops_speaker_words_returns_and_politics():
    mk = lambda st, sp='沟通要先听完': {'statement': st, 'source_spans': [{'exact_text': sp}]}
    kept, dropped = video_src.clean_units([mk('作者认为先倾听很重要。'), mk('先把对方的话听完再回应。'),
                                           mk('存够一笔钱就能覆盖开销。', '年化5%或6%，每年就有5万'), mk('政府政策影响收入。', '政府政策'),
                                           mk('每天固定半小时阅读。')])
    assert [u['statement'] for u in kept] == ['先把对方的话听完再回应。', '每天固定半小时阅读。'] and dropped == 3


# ---------------------------------------------------------------- routing / flag

def test_route_licence_frame_and_display_for_the_two_accounts():
    r = source_routes.route(video_src.SOURCE_ID)
    assert set(r['accounts']) == {'zh_longterm_investing', 'crypto_newbie_zh'} and r['beats']
    assert source_routes.allowed(SRC, 'zh_longterm_investing') and source_routes.allowed(SRC, 'crypto_newbie_zh')
    assert not source_routes.allowed(SRC, 'zh_macro') and not source_routes.allowed(SRC, 'crypto_diary_zh')
    assert registry.source_licence_tier(video_src.SOURCE_ID) == 'B'
    fr = attribution_frame.render('judgment_take', SRC, lang='zh')
    assert fr['text'] == '' and fr['names'] == [] and fr['credit_policy'] == 'own_voice' and '视频' in fr['never_name']
    assert source_display.display(SRC, 'zh')['ok']
    assert not attribution_frame.check('judgment_take', '每天固定半小时学习，坚持比强度重要。', fr, 'B') or \
        'provenance_in_body' not in {f['code'] for f in attribution_frame.check('judgment_take', '每天固定半小时学习。', fr, 'B')}


def test_flag_off_removes_route_licence_and_blocks_stored_units(monkeypatch):
    monkeypatch.setenv('FD_VIDEO_SRC', '0')
    source_routes._routes.cache_clear()
    assert source_routes.route(video_src.SOURCE_ID) is None
    assert registry.source_licence_tier(video_src.SOURCE_ID) is None
    assert not source_routes.allowed(SRC, 'zh_longterm_investing')
    assert video_src.registry_rows() == [] and video_src.licence_entries() == {}


def test_accounts_override_and_unknown_account_dropped(monkeypatch):
    monkeypatch.setenv('FD_VIDEO_ACCOUNTS', 'zh_longterm_investing,not_an_account')
    assert video_src.accounts() == ('zh_longterm_investing',)


# ---------------------------------------------------------------- compose-side rules

@pytest.mark.parametrize('body,code', [
    ('刚看到一个视频，说每天固定半小时学习最有效。', 'video_attribution'),
    ('有个博主讲过，沟通先听完再回应。', 'video_attribution'),
    ('同意 @someone 的看法，先听完再回应。', 'video_at_mention'),
    ('沟通的本质从某个角度来讲其实就是示弱，这一点值得反复体会。', 'video_verbatim'),
    ('慢下来的人并不是输了，而是在积累，先把基础打牢。', 'video_contrast'),
    ('ngl 这个习惯很难坚持，但值得试试。', 'video_ngl'),
    ('只要坚持定投，年化8%不是问题，稳赚不赔。', 'video_return_claim'),
    ('政府政策变化会直接影响每个人的收入预期。', 'video_politics'),
])
def test_findings_hard_blocks(body, code):
    assert code in {f['code'] for f in video_src.findings(body, SRC)}


def test_findings_clean_body_and_other_sources_untouched():
    clean = '先把对方的话听完，再决定要不要回应，很多争执就在这一步被省掉了。钱和时间都一样，慢一点反而省得多。'
    assert video_src.findings(clean, SRC) == []
    assert video_src.findings('刚看到一个视频，年化8%稳赚。', {'source_id': 'x_somebody'}) == []
    assert video_src.HARD_CODES <= set(__import__('live.qa_levels', fromlist=['HARD']).HARD)


def test_post_checks_classify_video_findings_as_hard():
    from live import qa_levels
    f = qa_levels.classify(video_src.findings('刚看到一个视频，说得很对。', SRC), frame_found=True)
    assert any(x['level'] == 'hard' for x in f if x['code'] == 'video_attribution') or \
        any(x.get('level') in ('HARD', 'hard') for x in f)


def test_weekly_cap_one_draft_per_account_per_week():
    ref = datetime(2026, 10, 16, 0, 13, tzinfo=timezone(timedelta(hours=1)))
    row = {'account_id': 'zh_longterm_investing', 'status': 'held', 'source': {'source_id': video_src.SOURCE_ID}}
    other = {'account_id': 'zh_longterm_investing', 'status': 'ready', 'source': {'source_id': 'x_foo'}}
    days = {'2026-10-12': [row, other]}
    assert video_src.weekly_blocked('zh_longterm_investing', ref, rows_for=lambda d: days.get(d, []))
    assert not video_src.weekly_blocked('crypto_newbie_zh', ref, rows_for=lambda d: [])
    days = {'2026-10-12': [dict(row, status='superseded')], '2026-10-01': [row]}
    assert not video_src.weekly_blocked('zh_longterm_investing', ref, rows_for=lambda d: days.get(d, []))


def test_fresh_enough_is_48h_from_post_time():
    ref = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    assert video_src.fresh_enough({'published_at': '2026-10-14T14:33:00+00:00'}, ref)
    assert not video_src.fresh_enough({'published_at': '2026-10-14T11:00:00+00:00'}, ref)
    assert not video_src.fresh_enough({}, ref)


# ---------------------------------------------------------------- candidates (selection)

def test_candidates_offer_video_units_only_to_routed_accounts_fresh_and_once_a_week(monkeypatch, tmp_path):
    from scripts import daily_compose as dc
    ref = datetime(2026, 10, 15, 22, 13, tzinfo=timezone.utc)
    recs = [dict(r, licence_tier='B') for r in UNITS]
    for r in recs:
        r['unit']['published_at'] = r['source']['published_at']
    monkeypatch.setattr(dc, 'units_for_persona', lambda store, beat, **kw: [r for r in recs if beat in r['tag_personas']])
    monkeypatch.setattr(dc, 'precheck', lambda account, options, diag=None: options)
    monkeypatch.setenv('FD_COMPOSE_INBOX', str(tmp_path))
    cfgs = {a['id']: a for a in __import__('live.fd_accounts', fromlist=['rows']).rows(ROOT / 'live/fd20_accounts.json')}

    def cand(account):
        a = cfgs[account]
        return dc.candidates(None, account, a['retrieval_beats'], {}, ref, account_cfg=a)
    pool = cand('zh_longterm_investing')
    assert pool and all(g[0]['source']['source_id'] == video_src.SOURCE_ID for g in pool)
    assert len(pool) == 1                                   # one video packet per account per call
    assert cand('crypto_newbie_zh')                         # crypto account: the crypto beat gate is skipped for it
    assert not any(g[0]['source']['source_id'] == video_src.SOURCE_ID for g in cand('zh_macro'))
    # 48 h: the same units 60 h later are not offered
    assert not [g for g in dc.candidates(None, 'zh_longterm_investing', cfgs['zh_longterm_investing']['retrieval_beats'], {},
                                         ref + timedelta(hours=60), account_cfg=cfgs['zh_longterm_investing'])
                if g[0]['source']['source_id'] == video_src.SOURCE_ID]
    # weekly cap: a draft from this source in the inbox 3 days ago blocks the next one
    day = tmp_path / '2026-10-12'
    day.mkdir()
    (day / 'd1.json').write_text(json.dumps({'id': 'd1', 'account_id': 'zh_longterm_investing', 'status': 'held',
                                             'source': {'source_id': video_src.SOURCE_ID}}))
    assert not cand('zh_longterm_investing')
    assert cand('crypto_newbie_zh')


def test_ingest_background_step_waits_only_for_the_budget(tmp_path):
    import subprocess
    import time
    p = subprocess.Popen(['sleep', '30'])
    res_path = tmp_path / 'r.json'
    t = time.monotonic()
    out = video_src.wait_background((p, res_path), wait_s=0.5)
    assert time.monotonic() - t < 5 and out['status'] == 'killed_at_budget' and p.poll() is not None
    p = subprocess.Popen(['true'])
    res_path.write_text(json.dumps({'status': 'ok', 'done': ['1'], 'failed_counts': {'9': 2}}))
    state = {}
    out = video_src.wait_background((p, res_path), wait_s=5)
    video_src.merge_result(state, out)
    assert out['done'] == ['1'] and state['video_src']['failed'] == {'9': 2}


def test_extract_one_transcript_per_call_filters_units_and_retries_empty_once():
    class Budget:
        def spent(self):
            return 0.0

        def set_cap(self, v):
            pass

        class BudgetExceeded(Exception):
            pass

    class Db:
        def __init__(self):
            self.added, self.tags = [], {}

        def add(self, src, units, adapter):
            self.added.append((src['id'], [u['unit_id'] for u in units], adapter))
            return {'added': len(units)}

        def set_persona_tags(self, tags, th):
            self.tags.update(tags)

    calls = []

    def fake_batch(group, client, **kw):
        calls.append([s['id'] for s in group])
        assert kw['licence_tier'] == 'B' and kw['prompt'] is not None
        good = {'unit_id': 'u1', 'statement': '先听完再回应能省掉很多争执。', 'source_spans': [{'exact_text': '先听完'}]}
        bad = {'unit_id': 'u2', 'statement': '作者说要先听完。', 'source_spans': [{'exact_text': '先听完'}]}
        return {group[0]['id']: ([good, bad] if group[0]['id'] == 'video-1' else [])}
    srcs = [{'id': 'video-1', 'source_id': video_src.SOURCE_ID, 'original_text': 'x'},
            {'id': 'video-2', 'source_id': video_src.SOURCE_ID, 'original_text': 'y'}]
    db, state = Db(), {}
    stats = video_src.extract(db, srcs, client=None, budget=Budget(), cost_cap_usd=1, fence_usd=0.2, state=state, now=NOW,
                              extract_batch=fake_batch)
    assert calls == [['video-1'], ['video-2']]                      # one transcript per call
    assert db.added == [('video-1', ['u1'], 'video_idea')] and stats['filtered_units'] == 1
    assert set(db.tags['u1']) == set(video_src.ROUTE_BEATS)         # deterministic route-beat tags
    assert state['video_src']['seen'] == ['video-1'] and state['video_src']['attempts'] == {'video-2': 1}
    video_src.extract(db, srcs[1:], client=None, budget=Budget(), cost_cap_usd=1, fence_usd=0.2, state=state, now=NOW,
                      extract_batch=fake_batch)
    assert 'video-2' in state['video_src']['seen']                  # an empty answer is retried once, then dropped
