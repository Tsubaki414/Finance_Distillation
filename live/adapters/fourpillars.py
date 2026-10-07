"""Four Pillars research articles -> dated sources for EXTRACT (Oct 7, fd20).

Four Pillars (https://4pillars.io, research at https://research.4pillars.io) is a public crypto research firm.
research.4pillars.io answers non-browser clients with a Vercel security checkpoint (HTTP 429 + JS challenge), and
we do not work around it. Their official newsletter, https://fourpillarsfp.substack.com/feed, is a plain public
RSS feed: every "FP Weekly" issue has a "Four Pillars Weekly" section that lists the week's research articles as

    <h3>: : <title> (<a href="https://research.4pillars.io/en/research/<slug>">Link</a>)</h3>
    <ul><li>key claim</li>...</ul>      (Four Pillars' own bullet summary of the article)

`articles()` turns that into one record per research article: {title, url, date, summary, key_claims, issue_title,
issue_url}; date is the issue's pubDate (the article came out that week). The same URL in several issues keeps the
earliest issue. `fetch()` makes one EXTRACT-ready source per article (title + bullets; never the full article,
which we do not fetch or republish).

Licence (live/source_licence.json fourpillars_research): tier B - reference and paraphrase allowed, short quotes
with attribution, no full-text republishing. Routing: live/source_routes.py (crypto research / DeFi / thesis
accounts only).
"""
from __future__ import annotations

import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from live.adapters import common

SOURCE_ID = 'fourpillars_research'
PUBLISHER = 'Four Pillars'
FEED_URL = 'https://fourpillarsfp.substack.com/feed'
SITE = 'https://research.4pillars.io'
ADAPTER = 'fourpillars'
USER_AGENT = 'FinanceDistillation-research-reader/1.0 (+RSS; public feed only)'
MAX_AGE_DAYS = 30
MIN_CLAIMS = 1

_NS = {'content': 'http://purl.org/rss/1.0/modules/content/'}
_H = re.compile(r'<h([1-4])[^>]*>(.*?)</h\1>', re.S | re.I)
_ARTICLE_URL = re.compile(r'href="(https://research\.4pillars\.io/[^"#?]+)"')
_LI = re.compile(r'<li[^>]*>(.*?)</li>', re.S | re.I)
_TAG = re.compile(r'<[^>]+>')


def _text(fragment):
    return re.sub(r'\s+', ' ', html.unescape(_TAG.sub(' ', fragment or ''))).strip()


def _title(heading):
    text = _text(re.sub(r'\(\s*<a[^>]*>.*?</a>\s*\)', '', heading, flags=re.S))
    return re.sub(r'^[:\s]+', '', text).strip()


def _date(value):
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def issue_articles(content, *, issue_title='', issue_url='', published=None):
    """Research articles listed in one issue's HTML: every heading that links to research.4pillars.io, with the
    bullet list between it and the next heading as key claims."""
    heads = list(_H.finditer(content or ''))
    out = []
    for i, h in enumerate(heads):
        m = _ARTICLE_URL.search(h.group(2))
        if not m:
            continue
        body = content[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(content)]
        claims = [c for c in (_text(li) for li in _LI.findall(body)) if c]
        out.append({'title': _title(h.group(2)), 'url': m.group(1).rstrip('/'),
                    'date': published.date().isoformat() if published else None,
                    'published_at': published.isoformat() if published else None,
                    'summary': claims[0] if claims else '', 'key_claims': claims,
                    'issue_title': issue_title, 'issue_url': issue_url})
    return out


def articles(feed_xml):
    """All research articles in the feed, newest issue first, one record per article URL (earliest issue wins)."""
    root = ET.fromstring(feed_xml)
    by_url = {}
    for item in root.iter('item'):
        published = _date(item.findtext('pubDate'))
        for a in issue_articles(item.findtext('content:encoded', namespaces=_NS) or '',
                                issue_title=(item.findtext('title') or '').strip(),
                                issue_url=(item.findtext('link') or '').strip(), published=published):
            prev = by_url.get(a['url'])
            if prev is None or (a['published_at'] or '') < (prev['published_at'] or ''):
                by_url[a['url']] = a
    return sorted(by_url.values(), key=lambda a: a['published_at'] or '', reverse=True)


def _get(url, timeout=40):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/rss+xml, application/xml'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def to_source(article):
    text = '\n\n'.join([article['title'], *article['key_claims']])
    return common.make_source(
        id=f'fp-{common.digest(article["url"])[:12]}', source_id=SOURCE_ID, text=text, publisher=PUBLISHER,
        title=article['title'], url=article['url'], published_at=article['published_at'], adapter=ADAPTER,
        author_name=PUBLISHER, lang='en',
        extra={'summary': article['summary'], 'key_claims': article['key_claims'],
               'issue_title': article['issue_title'], 'issue_url': article['issue_url'],
               'persona_hint': 'crypto_defi'})


def fetch(*, limit=None, max_age_days=MAX_AGE_DAYS, now=None, transport=None):
    """{'status', 'sources', 'articles'}: articles from the last max_age_days with >= MIN_CLAIMS key claims."""
    try:
        raw = (transport or _get)(FEED_URL)
        found = articles(raw)
    except Exception as exc:   # noqa: BLE001 - a feed failure is a channel status, not a crash
        return {'status': f'failed: {type(exc).__name__}: {str(exc)[:160]}', 'sources': [], 'articles': []}
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=max_age_days)).isoformat() if max_age_days else ''
    fresh = [a for a in found if len(a['key_claims']) >= MIN_CLAIMS and (a['published_at'] or '') >= cutoff]
    if limit:
        fresh = fresh[:limit]
    return {'status': 'ok' if fresh else 'empty', 'sources': [to_source(a) for a in fresh], 'articles': found}
