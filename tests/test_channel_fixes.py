"""Legal fixes for the channels that failed in the 2026-10-04 daily ingest."""
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import pytest
from live.adapters import channels, common

ROOT = Path(__file__).resolve().parents[1]
BODY = 'Public research explains financial markets and economic developments. ' * 40
ZH = '美股三大指数周五集体收涨，纳斯达克指数创下新高，市场关注下周公布的通胀数据与财报季开局。' * 45


def chan(cid):
    return next(c for c in channels.load_channels(ROOT/'live/channels.json') if c['channel_id'] == cid)


def test_user_agent_identifies_bot_honestly():
    ua = common.DEFAULT_UA
    assert 'compatible;' in ua and 'Bot' in ua and ('mailto:' in ua or 'http' in ua)
    assert 'Chrome' not in ua and 'Safari' not in ua   # no browser impersonation


def test_eastmoney_reports_send_required_date_window():
    calls = []
    def transport(url, headers):
        calls.append(url)
        return 200, json.dumps({'data': []})
    channels.fetch_channel(chan('ch001_data_eastmoney_com'), transport=transport)
    q = parse_qs(urlparse(calls[0]).query)
    assert q['beginTime'][0] < q['endTime'][0] and q['pageSize'][0] == '1'


def test_eastmoney_us_stock_columns_follow_articles():
    ch = chan('ch139_eastmoney_us_stock')
    assert ch['mode'] == 'json_api' and ch['lang'] == 'zh' and ch['persona_hint'] == 'zh_us_stock_commentary'
    calls = []
    def transport(url, headers):
        calls.append(url)
        if 'np-listapi' in url:
            return 200, json.dumps({'data': {'list': [{'title': '美股收评', 'showTime': '2026-10-04 08:00:00',
                     'uniqueUrl': 'http://finance.eastmoney.com/a/202610043888549456.html', 'mediaName': '券商中国'}]}})
        return 200, '<article><p>' + ZH + '</p></article>'
    out = channels.fetch_channel(ch, transport=transport)
    assert out['status'] == 'ok' and 'column=768' in calls[0]
    s = out['sources'][0]
    assert s['url'].startswith('https://finance.eastmoney.com/a/') and s['source_language'] == 'zh'
    assert s['published_at'].startswith('2026-10-04')


def test_feed_fulltext_uses_description_when_no_content():
    ch = chan('ch025_rss_art19_com')
    assert ch['mode'] == 'feed_fulltext'
    rss = ('<?xml version="1.0"?><rss version="2.0"><channel><title>T</title><item><title>Ep</title>'
           '<link>https://www.morganstanley.com/ideas/x</link><pubDate>Fri, 02 Oct 2026 20:00:00 -0000</pubDate>'
           '<description><![CDATA[<p>----- Transcript -----</p><p>' + BODY + '</p>]]></description></item></channel></rss>')
    calls = []
    def transport(url, headers):
        calls.append(url); return 200, rss
    out = channels.fetch_channel(ch, transport=transport)
    assert out['status'] == 'ok' and calls == [ch['feed_url']]   # never followed to the blocked site


def test_deny_patterns_respect_robots_rules():
    ch = chan('ch021_news_alphastreet_com')
    assert any('earnings-call' in p for p in ch['deny_url_patterns'])
    rss = ('<?xml version="1.0"?><rss version="2.0"><channel><title>A</title>'
           '<item><title>NVDA Q2 2027 Earnings Call Transcript</title><link>https://news.alphastreet.com/nvda-q2-2027-earnings-call/</link>'
           '<pubDate>Fri, 02 Oct 2026 20:00:00 -0000</pubDate><description>' + BODY + '</description></item>'
           '</channel></rss>')
    out = channels.fetch_channel(ch, transport=lambda u, h: (200, rss))
    assert not out['sources'] and 'robots' in out['radar'][0]['reason']


@pytest.mark.parametrize('cid', ['ch023_www_goldmansachs_com', 'ch026_www_morganstanley_com'])
def test_waf_blocked_bank_sites_are_excluded_with_substitute(cid):
    ch = chan(cid)
    assert ch['mode'] == 'excluded' and 'bot_challenge' in ch['reason'] and 'substitute' in ch['reason']


def test_nextplatform_is_marked_blocked_and_skipped():
    from scripts.run_content_adapters import newsletter_feeds
    assert 'nextplatform' not in {f['id'] for f in newsletter_feeds()}


def test_daily_ingest_default_cap_is_8():
    import inspect
    from live import daily_ingest
    assert inspect.signature(daily_ingest.run).parameters['cost_cap_usd'].default == 8.0


PODCAST = ('<?xml version="1.0"?><rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>'
           '<title>GS Exchanges</title><item><title>Rates outlook</title><pubDate>Thu, 01 Oct 2026 10:00:00 -0000</pubDate>'
           '<enclosure url="https://cdn.example/ep1.mp3" type="audio/mpeg" length="1"/></item></channel></rss>')


def test_local_whisper_podcast_source():
    from live.adapters import podcast_local
    ch = chan('ch024_feeds_megaphone_fm')
    got = []
    out = podcast_local.fetch(ch, limit=1, transport=lambda u, h: (200, PODCAST),
                              transcribe=lambda url: got.append(url) or BODY)
    assert got == ['https://cdn.example/ep1.mp3']
    s = out['sources'][0]
    assert out['status'] == 'ok' and s['adapter'] == 'podcast_whisper' and s['published_at'].startswith('2026-10-01')
    assert s['source_id'] == ch['channel_id'] and s['no_reproduction'] is True


def test_local_whisper_respects_tdm_reservation():
    from live.adapters import podcast_local
    rss = PODCAST.replace('<title>GS Exchanges</title>', '<title>GS</title><copyright>All rights reserved. Text and data mining reserved.</copyright>')
    out = podcast_local.fetch(chan('ch024_feeds_megaphone_fm'), transport=lambda u, h: (200, rss),
                              transcribe=lambda url: pytest.fail('must not transcribe'))
    assert out['status'] == 'tdm_reserved' and not out['sources']


def test_slow_channels_get_their_own_time_cap(tmp_path):
    import time
    from live.daily_ingest import run
    r = run(store=tmp_path/'s', runs_dir=tmp_path/'r', inbox=tmp_path/'i', state_path=tmp_path/'st.json',
            no_dashboard=True, channel_timeout=.02, channel_timeouts={'podcast:': 2},
            fetchers={'podcast:x': lambda: (time.sleep(.1) or {'sources': []})},
            extract=lambda s: [], backup=lambda: None, refresh=lambda: None)
    assert r['channels'][0]['status'] == 'ok'
