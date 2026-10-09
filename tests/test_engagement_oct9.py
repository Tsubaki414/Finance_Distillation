"""Oct 9 engagement pool review: huge authors need traction, watchlist ranked by donor traffic, search min_faves,
engage-only subscriptions for the daytime pulls (scripts/cron/engage_pull.sh)."""
import json
from datetime import datetime, timedelta, timezone

from live import engagement as E, x_breadth, x_daily

BJT = E.BJT
SLOT0 = datetime(2026, 10, 9, 16, 11, tzinfo=BJT)


def src(likes, views=3221, followers=406327, hours_before=1.5):
    pub = SLOT0 - timedelta(hours=hours_before)
    return {'url': 'https://x.com/fxtrader/status/2108447349748212003', 'published_at': pub.isoformat(),
            'source_language': 'zh', 'x_metrics': {'likes': likes, 'views': views, 'followers': followers,
                                                   'at': (pub + timedelta(minutes=15)).isoformat()}}


def test_huge_author_with_seven_likes_is_not_a_target():
    # 10-09: @fxtrader (406k) 7 likes / 3.2k views was picked as a reply target by the huge-author waiver
    assert E.assess(src(7), SLOT0)['reject'] == 'low_engagement'
    assert E.assess(src(E.config()['huge_min_likes']), SLOT0)['quote_ok']


def _donor(h, followers, cluster='acct_crypto_meme_zh', lang='zh'):
    return {'handle': h, 'followers': followers, 'persona_cluster': cluster, 'lang': lang, 'latest_post': '2026-10-08'}


def test_watchlist_ranks_by_traffic_and_drops_low_traffic(tmp_path, monkeypatch):
    donors = {d['handle'].lower(): d for d in [_donor('Huge_quiet', 900000), _donor('loud', 60000),
                                                _donor('mid', 80000), _donor('unknown', 200000)]}
    roster = tmp_path / 'roster.json'
    roster.write_text(json.dumps({'donors': donors}))
    monkeypatch.setattr(E, 'ROSTER', roster)
    posts = tmp_path / 'posts'
    posts.mkdir()
    for h, likes in (('huge_quiet', 5), ('loud', 400), ('mid', 60)):
        (posts / f'{h}.jsonl').write_text('\n'.join(json.dumps({'id': str(i), 'likes': likes}) for i in range(8)))
    traffic = E.donor_traffic(posts)
    assert traffic == {'huge_quiet': 5, 'loud': 400, 'mid': 60}
    rows = E.subscriptions([{'id': 'crypto_meme_zh', 'lang': 'zh', 'retrieval_beats': []}], traffic=traffic)
    assert [r['handle'] for r in rows] == ['loud', 'mid', 'unknown']   # sorted by handle; huge_quiet dropped
    cfg = dict(E.config(), targets_per_account=2)
    rows = E.subscriptions([{'id': 'crypto_meme_zh', 'lang': 'zh', 'retrieval_beats': []}], cfg=cfg, traffic=traffic)
    assert {r['handle'] for r in rows} == {'loud', 'mid'}                # known high-traffic first
    assert {r['handle']: r['median_likes'] for r in rows} == {'loud': 400, 'mid': 60}


def test_search_query_suffix():
    seen = []

    def search(q, cursor=None):
        seen.append(q)
        return {}
    now = datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc)
    subs = [{'handle': 'a', 'accounts': ['x']}, {'handle': 'b', 'accounts': ['x']}]
    x_breadth.fetch(subs, now=now, day='2099-01-01', window_hours=12, search=search,
                    config={'daily_call_cap': 5, 'batch_size': 20, 'pages_per_batch': 1, 'query_suffix': 'min_faves:30'},
                    log_name='test_engage_suffix')
    assert seen and seen[0].endswith(' min_faves:30') and 'from:a OR from:b' in seen[0]


def test_engage_subscriptions_are_engage_rows_with_beats():
    rows = x_daily.engage_subscriptions([{'id': 'crypto_macro_zh', 'lang': 'zh',
                                          'retrieval_beats': ['crypto_macro_zh', 'macro_zh']}])
    assert rows and all(r['engage'] and r['breadth'] and r['tier'] == 'B' for r in rows)
    assert all(r['beats'] == [['crypto_macro_zh', 'macro_zh']] for r in rows)
