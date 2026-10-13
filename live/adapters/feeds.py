"""Newsletters (Substack and other RSS, tier B) and podcasts (RSS + Podcasting 2.0
<podcast:transcript>). A feed whose rights notice reserves text-and-data mining /
computational analysis is never extracted (radar only)."""
from __future__ import annotations

import re

from live.adapters import common

TDM = re.compile(r'text and data mining|data mining|computational analysis|training (?:material|data)|'
                 r'artificial intelligence', re.I)


def parse_podcast(xml):
    copyright_ = ' '.join(re.findall(r'<copyright>(.*?)</copyright>', xml, re.S))
    items = []
    for block in re.findall(r'<item>(.*?)</item>', xml, re.S):
        title = (re.search(r'<title>(.*?)</title>', block, re.S) or [None, ''])[1]
        date = (re.search(r'<pubDate>(.*?)</pubDate>', block, re.S) or [None, ''])[1]
        tr = re.findall(r'<podcast:transcript\s+url="([^"]+)"\s+type="([^"]+)"', block)
        pick = next((u for u, t in tr if 'srt' in t or 'vtt' in t), tr[0][0] if tr else None)
        items.append({'title': common.html_text(title), 'published_raw': date.strip(),
                      'transcript_url': pick.replace('&amp;', '&') if pick else None})
    return {'copyright': copyright_.strip(), 'tdm_reserved': bool(TDM.search(copyright_)), 'items': items}


def srt_text(srt):
    lines = []
    for line in srt.splitlines():
        line = line.strip()
        if not line or line.isdigit() or '-->' in line or line.upper() == 'WEBVTT':
            continue
        lines.append(line)
    return re.sub(r'\s+', ' ', ' '.join(lines)).strip()


def fetch_podcast(feed_url, *, source_id, publisher, limit=1, transport=None):
    st, xml = common.http_get(feed_url, transport=transport)
    if st != 200:
        return {'status': f'http_{st}', 'sources': []}
    meta = parse_podcast(xml)
    if meta['tdm_reserved']:
        return {'status': 'tdm_reserved', 'copyright': meta['copyright'][:300], 'sources': [],
                'radar_titles': [i['title'] for i in meta['items'][:limit]]}
    sources = []
    for it in [i for i in meta['items'] if i['transcript_url']][:limit]:
        st, body = common.http_get(it['transcript_url'], transport=transport)
        if st == 200:
            text = srt_text(body)
            sources.append(common.make_source(id=f'pod-{source_id}-{common.digest(it["title"])[:10]}', source_id=source_id,
                                              text=text, publisher=publisher, title=it['title'], url=it['transcript_url'],
                                              published_at=_iso(it['published_raw']), adapter='podcast_rss'))
    return {'status': 'ok' if sources else 'no_transcripts', 'sources': sources}


def _iso(value):
    from email.utils import parsedate_to_datetime
    value = (value or '').strip()
    if re.match(r'\d{4}-\d{2}-\d{2}', value):
        return value[:10]
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return ''


def fetch_newsletter(feed, *, limit=1, min_chars=800, transport=None):
    """feed: source_registry row (id, name, feed_url). Uses the existing RSS reader."""
    from live.analysis_corpus import fetch_feed
    pf0 = feed.get('page_fetch') or {}
    if not feed.get('feed_url') and pf0.get('listing_url'):
        # Oct 13: HTML-listing site (no RSS): article links from the listing page, bodies via page_fetch below.
        from live.adapters import page_fetch
        links, error = page_fetch.listing_links(pf0, transport=transport, limit=limit)
        rows = [{'url': l['url'], 'title': l['title'], 'text': '', 'content_complete': False} for l in links]
    else:
        topic = feed.get('topic_filter')
        rows, error = fetch_feed({'id': feed['id'], 'author': feed.get('name'), 'url': feed['feed_url']},
                                 limit=max(limit * 6, 12) if topic else limit,
                                 **({'transport': transport} if transport is not None else {}))
        if topic and not error:
            # Oct 13: registry topic_filter (regex on title + feed text) keeps general feeds on the account angle.
            rx = re.compile(topic, re.I)
            rows = [r for r in rows if rx.search((r.get('title') or '') + ' ' + (r.get('text') or ''))][:limit]
    if error:
        return {'status': error, 'sources': []}
    sources, short, page_notes = [], 0, []
    pf = feed.get('page_fetch') or None
    for r in rows:
        text = r.get('text') or ''
        if (not r.get('content_complete') or len(text) < min_chars) and pf and r.get('url'):
            # Oct 13: summary-only feed opted in to a bounded article-page fetch (live/adapters/page_fetch.py).
            from live.adapters import page_fetch
            full, perr = page_fetch.article_text(r['url'], pf, transport=transport)
            page_notes.append({'url': r['url'], 'status': perr or 'ok'})
            if full and len(full) >= min_chars:
                r = {**r, 'text': full, 'content_complete': True, 'body_basis': 'page_fetch'}
                text = full
        if not r.get('content_complete') or len(text) < min_chars:
            short += 1
            continue
        sources.append(common.make_source(id=f'nl-{feed["id"]}-{common.digest(r.get("url") or text)[:10]}',
                                          source_id=feed['id'], text=text, publisher=feed.get('name') or feed['id'],
                                          title=r.get('title') or '', url=r.get('url') or '',
                                          published_at=_iso(r.get('published_at')), adapter='newsletter_rss',
                                          author_name=r.get('author_name'),
                                          lang=feed.get('lang') or feed.get('source_language') or 'en',
                                          extra={'persona_hint': feed.get('persona_hint')}))
    return {'status': 'ok' if sources else ('radar_only' if short else 'empty'), 'sources': sources,
            'items': len(rows), 'summary_only_items': short, 'page_fetch': page_notes,
            'radar_titles': [r.get('title', '') for r in rows if not r.get('content_complete') or len(r.get('text') or '') < min_chars]}
