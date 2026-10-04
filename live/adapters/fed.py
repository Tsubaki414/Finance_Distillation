"""Federal Reserve speeches, FOMC statements / minutes (tier A, primary_fed) via official RSS."""
from __future__ import annotations

import re
from email.utils import parsedate_to_datetime

from live.adapters import common

FEEDS = {'speech': 'https://www.federalreserve.gov/feeds/speeches.xml',
         'monetary': 'https://www.federalreserve.gov/feeds/press_monetary.xml'}


def _cdata(s):
    return re.sub(r'^<!\[CDATA\[|\]\]>$', '', (s or '').strip()).strip()


def parse_feed(xml, *, kind):
    items = []
    for block in re.findall(r'<item>(.*?)</item>', xml, re.S):
        get = lambda tag: _cdata((re.search(rf'<{tag}>(.*?)</{tag}>', block, re.S) or [None, ''])[1])
        date = get('pubDate')
        try:
            date = parsedate_to_datetime(date).date().isoformat()
        except (TypeError, ValueError):
            date = ''
        items.append({'title': common.html_text(get('title')), 'url': get('link'), 'published_at': date, 'kind': kind})
    return items


def article_text(html):
    m = re.search(r'<div[^>]+id="article"[^>]*>(.*?)<div[^>]+id="(?:footer|lastUpdate)', html, re.S)
    body = m.group(1) if m else (re.search(r'<div[^>]+id="article"[^>]*>(.*)', html, re.S) or [None, html])[1]
    return common.html_text(body)


def to_source(item, text):
    slug = item['url'].rstrip('/').rsplit('/', 1)[-1].replace('.htm', '')
    return common.make_source(id=f'fed-{slug}', source_id='primary_fed', text=text, publisher='Federal Reserve',
                              title=item['title'], url=item['url'], published_at=item['published_at'],
                              adapter='fed_rss', extra={'fed_kind': item['kind']})


def fetch(kind='speech', *, limit=2, transport=None):
    st, xml = common.http_get(FEEDS[kind], transport=transport)
    if st != 200:
        return {'status': f'http_{st}', 'sources': []}
    sources, requests = [], 1
    for it in parse_feed(xml, kind=kind)[:limit]:
        st, html = common.http_get(it['url'], transport=transport)
        requests += 1
        if st == 200:
            sources.append(to_source(it, article_text(html)))
    return {'status': 'ok', 'sources': sources, 'requests': requests}
