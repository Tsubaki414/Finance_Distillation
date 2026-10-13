import ipaddress
from unittest import mock
import pytest
from live.adapters import page_fetch, feeds
from live import source_recovery

ART = '<html><body><article id="post-1"><h1>T</h1>' + '<p>Tariffs raise prices for importers and consumers.</p>' * 40 + '</article></body></html>'


def tr(pages):
    def t(url, headers):
        return pages.get(url, (404, ''))
    return t


def setup_function(_):
    page_fetch._ROBOTS.clear()


def test_article_text_selector_and_robots():
    pages = {'https://ex.org/robots.txt': (200, 'User-agent: *\nDisallow: /private/'), 'https://ex.org/a': (200, ART)}
    cfg = {'allowed_hosts': ['ex.org'], 'body_selector': 'article[id^="post-"]'}
    text, err = page_fetch.article_text('https://ex.org/a', cfg, transport=tr(pages))
    assert err is None and 'Tariffs' in text
    assert page_fetch.article_text('https://ex.org/private/x', cfg, transport=tr(pages)) == (None, 'robots_disallow')
    assert page_fetch.article_text('https://other.org/a', cfg, transport=tr(pages)) == (None, 'host_not_allowed')


def test_access_block_is_not_bypassed():
    pages = {'https://ex.org/robots.txt': (404, ''), 'https://ex.org/a': (200, '<html><title>Request Access</title></html>')}
    assert page_fetch.article_text('https://ex.org/a', {'allowed_hosts': ['ex.org']}, transport=tr(pages))[1] == 'access_block'


def test_summary_feed_gets_full_text_via_page_fetch():
    rows = [{'url': 'https://ex.org/a', 'title': 'Tariff note', 'text': 'short', 'content_complete': False}]
    pages = {'https://ex.org/robots.txt': (404, ''), 'https://ex.org/a': (200, ART)}
    feed = {'id': 'x', 'feed_url': 'https://ex.org/feed', 'page_fetch': {'allowed_hosts': ['ex.org']}, 'topic_filter': 'tariff'}
    with mock.patch('live.analysis_corpus.fetch_feed', return_value=(rows, None)):
        out = feeds.fetch_newsletter(feed, limit=2, transport=tr(pages))
    assert out['status'] == 'ok' and len(out['sources']) == 1


def test_egress_proxy_scoped(monkeypatch):
    monkeypatch.delenv('FD_EGRESS_PROXY_IPS', raising=False)
    def ga(addrs):
        return lambda *a, **k: [(0, 0, 0, '', (x, 443)) for x in addrs]
    with mock.patch.object(source_recovery.socket, 'getaddrinfo', ga(['198.18.0.1'])):
        source_recovery.validate_url('https://ex.org/a', {'ex.org'})
    for bad in (['10.0.0.5'], ['198.18.0.1', '127.0.0.1'], ['198.18.0.2']):
        with mock.patch.object(source_recovery.socket, 'getaddrinfo', ga(bad)), pytest.raises(ValueError):
            source_recovery.validate_url('https://ex.org/a', {'ex.org'})
    monkeypatch.setenv('FD_EGRESS_PROXY_IPS', '')
    with mock.patch.object(source_recovery.socket, 'getaddrinfo', ga(['198.18.0.1'])), pytest.raises(ValueError):
        source_recovery.validate_url('https://ex.org/a', {'ex.org'})
