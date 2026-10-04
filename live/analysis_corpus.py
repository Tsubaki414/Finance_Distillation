"""Recent source ingestion for localization_v1.

Enabled adapters in source_registry.json are the actual subscriptions. Preserve
full extracted text and paragraph boundaries; save immutable source snapshots
alongside the latest corpus index. Unknown/truncated bodies remain incomplete.

The old REWRITE/MERGE classifier and event-search helpers below are retained for
legacy callers/tests only. Production uses live.distillation for account routing,
exact passage selection, translation, localization and fidelity QA.
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re, hashlib, datetime, subprocess, xml.etree.ElementTree as ET
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))

STORE = ROOT / 'live/store/analysis_corpus.jsonl'
REGISTRY = ROOT / 'live/source_registry.json'
RESEARCH = ROOT / 'live/research_sources.json'

# Recent enough to serve a live event. Not a year of archive.
WINDOW_DAYS = 21
PER_FEED = 6
PER_HANDLE = 8
# A headline relay is not a judgment. A short call with a ticker still is.
MIN_CHARS = 40

# Standing X subscriptions. Not the registry. The rest of the registry stays
# a candidate list and is not polled here.
PRIORITY_HANDLES = (
    'The_RockTrading',
    'qinbafrank',
    'PhyrexNi',
    'Murphychen888',
    'EmberCN',
    'liujiaolian',
    'HAOHONG_CFA',
    'citrini',
    'dylan522p',
)

# Standing feeds. The 22 added 2026-09-28 are already in research_sources.json
# and were verified on 2026-09-27. No new source.
# newsletter.semianalysis.com is the live feed. semianalysis.com/feed is not.
# Doomberg's live feed is newsletter.doomberg.com, not the stale substack URL
# recorded in research_sources.json.
# citrini the handle and citrini_feed are one author, two channels.
# Sportico is not in this list. It is an event lookup, not a subscription.
PRIORITY_FEEDS = (
    {'id': 'doomberg', 'author': 'Doomberg', 'url': 'https://newsletter.doomberg.com/feed', 'source_type': 'newsletter', 'persona': 'macro'},
    {'id': 'semianalysis', 'author': 'SemiAnalysis', 'url': 'https://newsletter.semianalysis.com/feed', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'citrini_feed', 'author': 'Citrini', 'url': 'https://www.citriniresearch.com/feed', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'overshoot', 'author': 'Matthew C. Klein', 'url': 'https://theovershoot.co/feed', 'source_type': 'newsletter', 'persona': 'macro'},
    {'id': 'conks', 'author': 'Conks', 'url': 'https://www.conks.plumbing/feed', 'source_type': 'newsletter', 'persona': 'macro'},
    {'id': 'hayes', 'author': 'Arthur Hayes', 'url': 'https://cryptohayes.substack.com/feed', 'source_type': 'newsletter', 'persona': 'macro'},
    {'id': 'dolphin', 'author': '海豚研究', 'url': 'https://wechat2rss.bestblogs.dev/feed/60b1f9007c87ab75cd83314bf5cfede30addd40a.xml', 'source_type': 'wechat', 'persona': 'industry'},
    {'id': 'chartbook', 'author': 'Adam Tooze', 'url': 'https://adamtooze.substack.com/feed', 'source_type': 'newsletter', 'persona': 'macro'},
    {'id': 'wolfstreet', 'author': 'Wolf Richter', 'url': 'https://wolfstreet.com/feed/', 'source_type': 'newsletter', 'persona': 'macro'},
    {'id': 'creditbubble', 'author': 'Doug Noland', 'url': 'https://creditbubblebulletin.blogspot.com/feeds/posts/default', 'source_type': 'newsletter', 'persona': 'macro'},
    {'id': 'libertystreet', 'author': 'Liberty Street Economics', 'url': 'https://libertystreeteconomics.newyorkfed.org/feed/', 'source_type': 'newsletter', 'persona': 'macro'},
    {'id': 'lynalden', 'author': 'Lyn Alden', 'url': 'https://www.lynalden.com/feed/', 'source_type': 'newsletter', 'persona': 'macro'},
    {'id': 'claudiasahm', 'author': 'Claudia Sahm', 'url': 'https://stayathomemacro.substack.com/feed', 'source_type': 'newsletter', 'persona': 'macro'},
    {'id': 'crisesnotes', 'author': 'Nathan Tankus', 'url': 'https://www.crisesnotes.com/feed', 'source_type': 'newsletter', 'persona': 'macro'},
    {'id': 'clausaasholm', 'author': 'Claus Aasholm', 'url': 'https://clausaasholm.substack.com/feed', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'semiengineer', 'author': 'The Semiconductor Engineer', 'url': 'https://thesemiconductornewsletter.substack.com/feed', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'tmtb', 'author': 'TMTB', 'url': 'https://tmtbreakout.substack.com/feed', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'netinterest', 'author': 'Marc Rubinstein', 'url': 'https://www.netinterest.co/feed', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'nextplatform', 'author': 'The Next Platform', 'url': 'https://www.nextplatform.com/feed/', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'servethehome', 'author': 'ServeTheHome', 'url': 'https://www.servethehome.com/feed/', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'stratechery', 'author': 'Ben Thompson', 'url': 'https://stratechery.com/feed/', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'rbnenergy', 'author': 'RBN Energy', 'url': 'https://rbnenergy.com/rss.xml', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'acquired', 'author': 'Acquired', 'url': 'https://www.acquired.fm/episodes?format=rss', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'fabricatedknowledge', 'author': 'Fabricated Knowledge', 'url': 'https://www.fabricatedknowledge.com/feed', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'damodaran', 'author': 'Aswath Damodaran', 'url': 'https://aswathdamodaran.blogspot.com/feeds/posts/default', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'asymco', 'author': 'Horace Dediu', 'url': 'https://www.asymco.com/feed/', 'source_type': 'newsletter', 'persona': 'industry'},
    {'id': 'traderfeed', 'author': 'Brett Steenbarger', 'url': 'https://traderfeed.blogspot.com/feeds/posts/default', 'source_type': 'newsletter', 'persona': 'trading'},
    {'id': 'moontower', 'author': 'Kris Abdelmessih', 'url': 'https://moontowermeta.com/rss/', 'source_type': 'newsletter', 'persona': 'trading'},
    {'id': 'perceptivetrader', 'author': 'The High-Performing Trader', 'url': 'https://theperceptivetrader.substack.com/feed', 'source_type': 'newsletter', 'persona': 'trading'},
    {'id': 'asymtrading', 'author': 'AsymTrading', 'url': 'https://asymtrading.substack.com/feed', 'source_type': 'newsletter', 'persona': 'trading'},
    {'id': 'algomatic', 'author': 'Algomatic Trading', 'url': 'https://algomatictrading.substack.com/feed', 'source_type': 'newsletter', 'persona': 'trading'},
    {'id': 'kieranduff', 'author': 'Kieran Duff', 'url': 'https://kieranduff.substack.com/feed', 'source_type': 'newsletter', 'persona': 'trading'},
)

# Home persona of a standing subscription. The classifier may still pick
# another voice from the words. This map is coverage, not a template.
HANDLE_PERSONA = {
    'The_RockTrading': 'trading',
    'qinbafrank': 'macro',
    'PhyrexNi': 'macro',
    'Murphychen888': 'macro',
    'EmberCN': 'macro',
    'liujiaolian': 'macro',
    'HAOHONG_CFA': 'macro',
    'citrini': 'industry',
    'dylan522p': 'industry',
}
FEED_PERSONA = {row['id']: row['persona'] for row in PRIORITY_FEEDS}

# Promo and match chat are not rewrite material.
_DROP = re.compile(
    r'join us|link in profile|use code|patreon|订阅|课程|加群',
    re.I,
)
_TICKER = re.compile(r'\$([A-Za-z]{1,5})\b')
_WORD = re.compile(r'[A-Za-z][A-Za-z0-9]{2,}|[一-鿿]{2,}')


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in (
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S %Z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S.%f%z',
    ):
        try:
            d = datetime.datetime.strptime(text.replace('Z', '+0000'), fmt)
        except ValueError:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return d
    try:
        d = datetime.datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d


def _rid(source_id, url, title):
    blob = (source_id or '') + '|' + (url or '') + '|' + (title or '')
    return hashlib.sha1(blob.encode('utf-8')).hexdigest()[:16]


def _entities(text):
    found = []
    for tok in _TICKER.findall(text or ''):
        low = tok.lower()
        if low not in found:
            found.append(low)
    return found


def load():
    rows = []
    if not STORE.is_file():
        return rows
    for line in STORE.read_text(encoding='utf-8').split('\n'):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def save(rows):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    # One row per id. A later fetch of the same url replaces the text.
    by_id = {}
    for row in rows:
        from live.distillation_source import source_record, snapshot
        snapshot(source_record(row), STORE.parent / 'source_snapshots')
        by_id[row.get('id') or _rid(row.get('source_id'), row.get('url'), row.get('title'))] = row
    ordered = sorted(by_id.values(), key=lambda r: r.get('published_at') or '', reverse=True)
    temporary = STORE.with_suffix('.jsonl.tmp')
    temporary.write_text(
        ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in ordered),
        encoding='utf-8',
    )
    temporary.replace(STORE)
    return ordered


def _fresh(published_at, now=None, days=WINDOW_DAYS):
    d = _parse(published_at)
    if not d:
        return True
    return ((now or _now()) - d).total_seconds() <= days * 86400


def _row(source_id, author, published_at, title, text, url, source_type,
         content_complete=False, extraction_status='completeness_unknown', **metadata):
    # Original extraction is immutable; normalization is a separate field.
    text = text or ''
    title = re.sub(r'\s+', ' ', (title or '')).strip()
    if not text.strip() and not title:
        return None
    body = text or title
    row = {
        'id': _rid(source_id, url, title or body[:80]),
        'source_id': source_id,
        'author': author,
        'published_at': published_at,
        'title': title[:240],
        'text': body,
        'url': url,
        'entities': _entities(title + ' ' + body),
        'source_type': source_type,
        'content_complete': content_complete,
        'extraction_status': extraction_status,
        'extractor_version': 'analysis-corpus-v2',
        'fetched_at': _now().isoformat(),
        **metadata,
    }
    from live.distillation_source import source_record
    contract = source_record(row)
    row.update({k: contract[k] for k in ('source_hash', 'source_version', 'original_text',
                                       'normalized_text', 'source_language', 'language_confidence')})
    return row


def _local(tag):
    name = re.sub(r'\{[^}]+\}', '', tag)
    return name


class _FeedText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
        self.media = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        tag = tag.split(':')[-1]
        if tag in ('script', 'style'):
            self.hidden += 1
        attrs = dict(attrs)
        if tag == 'img':
            self.media.append({'url': attrs.get('src'), 'alt': attrs.get('alt', ''), 'read': False})
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'pre':
            self.parts.append('\n\n```\n')
        if tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'blockquote'):
            self.parts.append('\n\n')

    def handle_endtag(self, tag):
        tag = tag.split(':')[-1]
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1
        if tag in ('p', 'div', 'li', 'blockquote'):
            self.parts.append('\n\n')
        if tag == 'pre':
            self.parts.append('\n```\n\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _feed_body(item, with_metadata=False):
    # Prefer ONE full content field; appending description duplicates the lead.
    for name in ('encoded', 'content', 'description', 'summary'):
        child = next((c for c in item if _local(c.tag) == name), None)
        if child is not None:
            parser = _FeedText()
            raw = ''.join(child.itertext()) if not list(child) else ''.join(ET.tostring(c, encoding='unicode') for c in child)
            parser.feed(raw)
            text = ''.join(parser.parts).strip()
            if text:
                teaser = bool(re.search(r'continue reading|read (?:the full|more)|paid subscribers|付费阅读|阅读全文|…\s*$', text, re.I))
                # Presence of content is extraction evidence, not proof of article completeness.
                result = (text, name in ('encoded', 'content') and not teaser, name)
                return (*result, {'media': parser.media, 'external_links': parser.links}) if with_metadata else result
    return ('', False, 'missing', {'media': [], 'external_links': []}) if with_metadata else ('', False, 'missing')


def _text_of(item):
    return _feed_body(item)[0]


def fetch_feed(feed, limit=PER_FEED, transport=None):
    """One RSS/Atom URL. A failed fetch returns no rows and a note."""
    if transport is not None:
        from live.adapters.common import http_get
        status, xml = http_get(feed['url'], transport=transport)
        if status != 200:
            return [], f'http_{status}'
    else:
        cmd = ['curl', '-fsSL', '--max-time', '25', '-A', 'Mozilla/5.0', feed['url']]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return [], type(exc).__name__
        if r.returncode != 0 or not (r.stdout or '').strip():
            return [], 'fetch_failed'
        xml = r.stdout
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return [], 'not_xml'
    items = root.findall('.//item')
    if not items:
        items = [e for e in root.iter() if _local(e.tag) == 'entry']
    rows = []
    for item in items[:limit]:
        title = ''
        link = ''
        published = ''
        creators, authors = [], []
        for child in list(item):
            name = _local(child.tag)
            if name == 'title' and not title:
                title = ''.join(child.itertext()).strip()
            elif name == 'link' and not link:
                link = (child.text or child.get('href') or '').strip()
            elif name in ('pubDate', 'published', 'updated', 'date') and not published:
                published = (child.text or '').strip()
            elif name == 'creator':
                creator = ''.join(child.itertext()).strip()
                if creator:
                    creators.append(creator)
            elif name == 'author':
                # Atom authors have a nested name; RSS author strings remain
                # exact publisher-supplied identities, never guessed from prose.
                named = next((node for node in child if _local(node.tag) == 'name'), None)
                author = ''.join((named if named is not None else child).itertext()).strip()
                if author:
                    authors.append(author)
        text, complete, field, metadata = _feed_body(item, with_metadata=True)
        publisher = feed.get('author') or feed['id']
        names = list(dict.fromkeys(creators or authors))
        author = ', '.join(names) if names else publisher
        author_basis = 'feed_creator' if creators else 'feed_author' if authors else 'publisher_fallback_no_article_author'
        identity_metadata = {'kind': 'feed_author_metadata', 'publisher_name': publisher,
                             'author_name': author, 'author_basis': author_basis,
                             'identity_scope': 'article_author' if names else 'publisher_only'}
        row = _row(feed['id'], author, published, title, text or title, link,
                   feed.get('source_type') or 'newsletter', content_complete=complete,
                   extraction_status='feed_' + field, body_recovery='public_html',content_kind='article',
                   author_name=author, publisher_name=publisher, author_basis=author_basis,
                   context_items=[identity_metadata], **metadata)
        if row:
            rows.append(row)
    return rows, None


def fetch_handle(handle, limit=PER_HANDLE):
    """Recent posts from one X account. Search is not used here."""
    cmd = ['twitter', 'user-posts', '@' + handle.lstrip('@'), '-n', str(limit), '--json']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return [], type(exc).__name__
    raw = r.stdout or ''
    start = raw.find('{')
    if start < 0:
        return [], 'no_json'
    try:
        data = json.loads(raw[start:])
    except json.JSONDecodeError:
        return [], 'bad_json'
    if not data.get('ok'):
        return [], (data.get('error') or {}).get('code') or 'not_ok'
    rows = []
    for post in data.get('data') or []:
        if post.get('isRetweet'):
            continue
        note = post.get('noteTweet') or {}
        text = post.get('fullText') or (note.get('text') if isinstance(note, dict) else '') or post.get('text') or ''
        published = post.get('createdAtISO') or ''
        url = 'https://x.com/' + handle + '/status/' + str(post.get('id') or '')
        complete = not post.get('truncated') and not re.search(r'(?:…|\.\.\.)\s*(?:https?://\S+)?$', text)
        row = _row('x_' + handle, handle, published, '', text, url, 'x',
                   content_complete=bool(complete), extraction_status='x_post',
                   author_id=post.get('authorId') or post.get('userId'),
                   post_type=post.get('post_type') or ('reply' if post.get('inReplyToStatusId') else 'original'),
                   reply_to=post.get('reply_to') or post.get('inReplyToStatusId'),
                   quoted_post=post.get('quoted_post') or post.get('quotedStatus') or post.get('quotedStatusId'),
                   thread_id=post.get('conversationId'), truncated=bool(post.get('truncated')),
                   media=post.get('media') or [], external_links=post.get('urls') or [],
                   media_dependencies=[],body_recovery='archive_only',content_kind='post')
        if row:
            rows.append(row)
    return rows, None


def subscriptions():
    registry = json.loads(REGISTRY.read_text())
    enabled = [r for r in registry['sources'] if r.get('enabled') is True]
    handles = [r['handle'] for r in enabled if r.get('adapter') == 'x']
    feeds = [{'id': r['id'], 'author': r.get('author') or r.get('name'),
              'url': r['feed_url'], 'source_type': r.get('source_type', 'newsletter')}
             for r in enabled if r.get('adapter') == 'feed']
    return handles, feeds


def collect(handles=None, feeds=None, existing=None):
    """Refresh the recent window. Does not crawl history."""
    enabled_handles, enabled_feeds = subscriptions()
    handles = list(handles if handles is not None else enabled_handles)
    feeds = list(feeds if feeds is not None else enabled_feeds)
    rows = list(existing if existing is not None else load())
    notes = []
    added = 0
    known = {r.get('id') for r in rows}
    for feed in feeds:
        got, note = fetch_feed(feed)
        if note:
            notes.append({'source': feed['id'], 'note': note})
        for row in got:
            if not _fresh(row.get('published_at')):
                continue
            if row['id'] not in known:
                added += 1
                known.add(row['id'])
            rows.append(row)
    for handle in handles:
        got, note = fetch_handle(handle)
        if note:
            notes.append({'source': handle, 'note': note})
        for row in got:
            if not _fresh(row.get('published_at')):
                continue
            if row['id'] not in known:
                added += 1
                known.add(row['id'])
            rows.append(row)
    saved = save(rows)
    return {'rows': len(saved), 'added': added, 'notes': notes}


def _terms(packet):
    """Names and tickers the event is actually about. Not every word."""
    terms = []
    for token in packet.get('support') or []:
        if str(token).startswith('alias:'):
            continue
        if len(str(token)) >= 3:
            terms.append(str(token).lower())
    title = packet.get('title') or ''
    for tok in _WORD.findall(title):
        if len(tok) >= 4:
            terms.append(tok.lower())
    for view in packet.get('source_views') or []:
        claim = view.get('claim') or ''
        for tok in _TICKER.findall(claim):
            terms.append(tok.lower())
    # Dedup, longest first so "kalshi" wins over a short token.
    out = []
    for t in sorted(set(terms), key=len, reverse=True):
        if t not in out and t not in ('news', 'with', 'from', 'that', 'this', 'says'):
            out.append(t)
    return out[:12]


# Names that show up in almost every market post. Matching them does not
# mean the post is about this event.
_GENERIC = {
    'bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'market', 'stock', 'stocks',
    'openai', 'nvidia', 'google', 'apple', 'tesla', 'fed', 'with', 'from',
    'news', 'that', 'this', 'says', 'tron',
}


def _event_terms(terms):
    """The names that identify the event, not the assets everyone mentions.

    A cluster whose only token is bitcoin matches every market post.
    That is not a reading of the event. Return nothing rather than the
    whole window.
    """
    return [t for t in terms if t not in _GENERIC and len(t) >= 4]


def _score(row, terms):
    blob = ((row.get('title') or '') + ' ' + (row.get('text') or '')).lower()
    specific = _event_terms(terms)
    hits = [t for t in specific if t and t in blob]
    if not hits:
        hits = [t for t in specific if t in (row.get('entities') or [])]
    if not hits:
        return 0, []
    # One mention in a long unrelated piece is not a reading of this event.
    # The name has to carry the piece, or the piece has to be short.
    text = row.get('text') or ''
    lead = (text[:400] + ' ' + (row.get('title') or '')).lower()
    in_lead = [t for t in hits if t in lead]
    if not in_lead and len(text) > 500:
        return 0, hits
    recency = 0
    d = _parse(row.get('published_at'))
    if d:
        age_h = max(0, (_now() - d).total_seconds() / 3600)
        recency = max(0, 72 - age_h) / 72
    return len(hits) * 2 + (1 if in_lead else 0) + recency, hits


def match_event(packet, rows=None, limit=6):
    """Recent analyst rows about this event. Empty is a real answer.

    Ranking is term overlap plus recency. A wire reprint of the headline
    scores, but a longer judgment outranks a short relay of the same terms.
    """
    rows = rows if rows is not None else load()
    terms = _terms(packet)
    ranked = []
    for row in rows:
        score, hits = _score(row, terms)
        if score <= 0:
            continue
        text = row.get('text') or ''
        # A judgment outranks a longer piece that only shares the name.
        judgment = 1.5 if re.search(
            r'不是|不会|没有|没有人|why |because|rather than|not a ', text, re.I
        ) else 0
        length_boost = min(len(text) / 1200, 1.2)
        ranked.append((score + judgment + length_boost, hits, row))
    ranked.sort(key=lambda x: x[0], reverse=True)
    picked = []
    seen_author = {}
    for score, hits, row in ranked:
        author = row.get('author') or row.get('source_id')
        # One author can contribute two pieces. Five relays from one desk
        # are not five judgments.
        if seen_author.get(author, 0) >= 2:
            continue
        seen_author[author] = seen_author.get(author, 0) + 1
        picked.append({
            'source': row.get('source_id'),
            'author': author,
            'url': row.get('url'),
            'published_at': row.get('published_at'),
            'title': row.get('title'),
            'original_text': (row.get('text') or '')[:1800],
            'matched_terms': hits,
            'source_type': row.get('source_type'),
        })
        if len(picked) >= limit:
            break
    return picked


# Accounts whose timeline is worth reading when an event names their subject.
# This is not a new source pool. It is where to look when the standing
# window has not written about the event yet.
SUBJECT_HANDLES = (
    ('alpenglow', 'TheWattenhofer'),
    ('solana', 'TheWattenhofer'),
    ('kalshi', 'DustinGouker'),
)


def search_event(packet, limit=8):
    """Directed search when the recent corpus has nothing on this event.

    Uses the browser-backed search, not the CLI keyword search, which
    returns 404. A hit is appended to the corpus by the caller. A failed
    search returns no rows. It does not invent a judgment.
    """
    terms = _terms(packet)
    if not terms:
        return []
    query = ' '.join(terms[:3])
    cmd = [
        'opencli', 'twitter', 'search', query,
        '--product', 'live', '--limit', str(limit), '-f', 'json',
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=50)
    except (subprocess.TimeoutExpired, OSError):
        return []
    raw = r.stdout or ''
    start = raw.find('[')
    if start < 0:
        return []
    try:
        data = json.loads(raw[start:])
    except json.JSONDecodeError:
        return []
    rows = []
    for post in data:
        if not isinstance(post, dict):
            continue
        author = post.get('author') or ''
        text = post.get('text') or ''
        published = post.get('created_at') or ''
        url = post.get('url') or ''
        row = _row('x_' + author, author, published, '', text, url, 'x')
        if not row:
            continue
        score, hits = _score(row, terms)
        if score <= 0:
            continue
        # A headline relay is not a judgment. A market wrap that only
        # names the subject is not one either.
        if re.search(r'\bETF\b|inflow|join us|use code', text, re.I):
            continue
        if not re.search(r'[?？]|不是|不会|没有|i think|imo|why |because|而非|而不是', text, re.I):
            if len(text) < 180:
                continue
        row['matched_terms'] = hits
        rows.append(row)
    # The standing window missed this subject. Read the account that
    # actually works on it, instead of the first eight people who retweeted.
    terms = _terms(packet)
    seen = {row.get('author') for row in rows}
    for needle, handle in SUBJECT_HANDLES:
        if needle not in terms or handle in seen:
            continue
        got, note = fetch_handle(handle, limit=6)
        if note:
            continue
        for row in got:
            score, hits = _score(row, terms)
            if score <= 0:
                continue
            row['matched_terms'] = hits
            rows.append(row)
            seen.add(handle)
            break
    return rows


def rewrite_from_matches(matches):
    """The shape public_writer already reads. Excerpt stays attached."""
    pieces = []
    for row in matches:
        text = row.get('original_text') or row.get('text') or ''
        pieces.append({
            'source': row.get('source') or row.get('source_id'),
            'author': row.get('author'),
            'url': row.get('url'),
            'main_thesis': (row.get('title') or text[:180]).strip(),
            'reasoning_chain': '',
            'interesting_angle': '',
            'second_order_implication': '',
            'disagreement_with_others': '',
            'original_text': text,
        })
    return pieces


# --- source-first classification ------------------------------------------------
# A new post is judged on its own words. Matching against other posts happens
# only when the label would be MERGE.

MERGE_WINDOW_HOURS = 72

# Ads and life posts. A promo code is already dropped at ingest; these catch
# the ones that still land in the window. A broker tagline stapled under a
# market note is not itself the post.
_AD = re.compile(
    r'link in bio|giveaway|airdrop|注册即送|开户|邀请码|课程顾问|私信我|加微信|'
    r'join (?:us|our)|sign up|subscribe to|订阅后可见|付费墙',
    re.I,
)
_PROMO_TAIL = re.compile(
    r'来了就是\s*VIP|全球先机一站布局|link in profile|use code',
    re.I,
)
_LIFE = re.compile(
    r'生日快乐|早安|晚安|good morning|happy birthday|'
    r'thank you to the waymo|as i was getting out',
    re.I,
)
# Judgment markers. A post without one of these is a recap or a tape note.
# "不是……而是" is a judgment. A bare "不是" inside "不是就空掉" is not,
# so the short form is not listed on its own.
_JUDGMENT = re.compile(
    r'不是[^，。]{0,12}而是|不会|所以|因为|意味着|问题是|我认为|我觉得|我的观点|'
    r'值得|关键是|反而|不同于|忽略|背离|概率|可能|为什么|而非|而不是|'
    r'相似|说明|虽然|但是|忽略了|不同点|'
    r'why |because|rather than|not a |i think|imo|the point|means that|'
    r'instead of|the real|what matters|should be|the same should|'
    r'support level|range bound|gap down|fills by|catalyst',
    re.I,
)
_REASONING = re.compile(
    r'因为|所以|原因|逻辑|如果|那么|一方面|另一方面|首先|其次|'
    r'because|therefore|the reason|which means|so that',
    re.I,
)

# Specific names worth clustering on. Generic market words do not make two
# posts "the same thing."
_CLUSTER_STOP = _GENERIC | {
    'today', 'week', 'weeks', 'year', 'years', 'price', 'prices', 'share',
    'shares', 'company', 'companies', 'index', 'just', 'still', 'after',
    'before', 'about', 'their', 'there', 'would', 'could', 'should',
    'the', 'and', 'for', 'are', 'was', 'has', 'have', 'not', 'but',
    'you', 'your', 'our', 'its', 'into', 'over', 'under', 'than',
    'what', 'when', 'where', 'which', 'who', 'how', 'why', 'all',
    'one', 'two', 'new', 'now', 'out', 'per', 'via',
    'they', 'them', 'this', 'that', 'these', 'those', 'well', 'thing',
    'things', 'here', 'been', 'were', 'will', 'with', 'from', 'have',
    'more', 'most', 'some', 'such', 'only', 'also', 'than', 'then',
    'into', 'over', 'very', 'just', 'like', 'make', 'made', 'much',
    'many', 'other', 'since', 'while', 'where', 'which', 'whose',
    '今天', '昨天', '市场', '目前', '已经', '这个', '一个', '我们', '他们',
    '就是', '还是', '可以', '没有', '不是', '因为', '所以', '如果', '但是',
    '以及', '进行', '开始', '通过', '对于', '关于', '其中', '同时', '之后',
    '数据', '公司', '股价', '上涨', '下跌', '表示', '认为', '看到', '现在',
    '的资金', '资金',
}

# Persona seeds. A picker, not a new voice and not a template.
_PERSONA_TRADING = re.compile(
    r'支撑|压力|仓位|止损|缺口|gap|support|resistance|心理|共识|确认|'
    r'作废|fills by|catalysts this week|bounce',
    re.I,
)
_PERSONA_INDUSTRY = re.compile(
    r'回购|产业链|护城河|毛利|出货|产能|buyback|repurchase|supply chain|'
    r'光模块|光引擎|材料|客户|订单|份额|teardown|datacenter|gpu',
    re.I,
)
_PERSONA_MACRO = re.compile(
    r'流动性|美债|收益率|准备金|加息|降息|油价|美元|etf|资金流|净流入|净流出|'
    r'yield|liquidity|reserves|rate hike|oil|brent|wti',
    re.I,
)


def connected_rows(rows=None,source_ids=None):
    """Rows from the sources this file actually polls.

    A directed search can leave other authors in the jsonl. They are not
    part of the subscription, so the source-first loop does not read them.
    """
    rows = rows if rows is not None else load()
    if source_ids is None:
        enabled_handles,enabled_feeds=subscriptions()
        registry=json.loads(REGISTRY.read_text())
        source_ids={r['id'] for r in registry['sources'] if r.get('enabled') is True}
        # Keep historical X IDs at the adapter boundary. Core intake admits
        # normalized rows by subscribed source ID, independent of platform.
        source_ids.update('x_'+h for h in enabled_handles)
        source_ids.update(f['id'] for f in enabled_feeds)
    else:source_ids=set(source_ids)
    out = []
    for row in rows:
        sid = row.get('source_id') or ''
        if sid in source_ids:
            out.append(row)
    return out


def _sort_key(row):
    return _parse(row.get('published_at')) or datetime.datetime.min.replace(
        tzinfo=datetime.timezone.utc)


def latest(n=20, rows=None):
    """Newest n subscribed items. Undated rows sort last.

    Kept for a raw recency check. Production uses intake(), which caps
    each source so a fast account cannot fill the window.
    """
    dated = sorted(connected_rows(rows), key=_sort_key, reverse=True)
    return dated[:n]


def intake(rows=None, per_source=2, hours=24, now=None,source_ids=None):
    """Unprocessed items for one source-first round.

    Each subscribed source contributes at most `per_source` items from the
    last `hours`. A source with nothing in that window contributes nothing.
    Order is round-robin by recency, so the first pass already has one item
    from each active source before anyone gets a second.
    """
    now = now or _now()
    buckets = {}
    for row in connected_rows(rows,source_ids):
        published = _parse(row.get('published_at'))
        if not published:
            continue
        if (now - published).total_seconds() > hours * 3600:
            continue
        buckets.setdefault(row.get('source_id') or '', []).append(row)
    for sid in buckets:
        buckets[sid].sort(key=_sort_key, reverse=True)
        buckets[sid] = buckets[sid][:per_source]
    # Newest source first, then one item per source, then the second.
    order = sorted(buckets, key=lambda sid: _sort_key(buckets[sid][0]), reverse=True)
    picked = []
    for slot in range(per_source):
        for sid in order:
            if slot < len(buckets[sid]):
                picked.append(buckets[sid][slot])
    return picked


def _blob(row):
    return ((row.get('title') or '') + '\n' + (row.get('text') or '')).strip()


def _body(text):
    """Drop a stapled promo line. The market note above it still counts."""
    kept = []
    for line in (text or '').splitlines():
        if _PROMO_TAIL.search(line) and len(line.strip()) < 80:
            continue
        kept.append(line)
    return '\n'.join(kept).strip()


def _is_relay(text):
    """A headline pasted through, not a judgment.

    All-caps is how some tape accounts write a real call, so caps alone
    are not a relay. A relay is a short post that restates an announcement
    and never says what the author makes of it.
    """
    raw = _body(text)
    if _has_judgment(raw):
        return False
    letters = re.sub(r'[^A-Za-z]', '', raw)
    if len(letters) >= 24:
        upper = sum(1 for c in letters if c.isupper())
        if upper / len(letters) >= 0.85 and len(raw) < 280:
            return True
    return False


def _has_judgment(text):
    if _JUDGMENT.search(text or ''):
        return True
    if _REASONING.search(text or '') and len(text or '') >= 80:
        return True
    return False


def _topic_keys(row):
    """Entities and specific names. Generic market words are not a topic."""
    keys = []
    for ent in row.get('entities') or []:
        low = str(ent).lower()
        if low and low not in _CLUSTER_STOP and low not in keys:
            keys.append(low)
    blob = _blob(row)
    # Latin names of products, people, places. Tickers already live in entities.
    for tok in re.findall(r'\b[A-Z][A-Za-z0-9]{2,}\b', blob):
        low = tok.lower()
        if low in _CLUSTER_STOP or low in keys or len(low) < 4:
            continue
        keys.append(low)
    for tok in re.findall(r'[一-鿿]{2,8}', blob):
        if tok in _CLUSTER_STOP or tok in keys:
            continue
        # A two-character function word is not a subject.
        if len(tok) < 3 and tok not in ('原油', '美债', '英伟达', '比特币'):
            continue
        keys.append(tok)
    return keys[:16]


def _lead_keys(row):
    """Names in the title and the opening. A name buried in an example is not the subject."""
    lead = ((row.get('title') or '') + ' ' + (row.get('text') or '')[:180]).strip()
    return set(_topic_keys({'title': '', 'text': lead, 'entities': row.get('entities') or []}))


def _subject_key(key):
    if key in _CLUSTER_STOP:
        return False
    if key.isascii():
        return len(key) >= 6
    return len(key) >= 4


def _same_subject(a, b):
    """Same thing means the same name leads both pieces.

    A ticker both posts tag counts. A name that only shows up as an
    example halfway through does not.
    """
    tickers = set(a.get('entities') or []) & set(b.get('entities') or [])
    if any(t for t in tickers if t not in _CLUSTER_STOP):
        return True
    shared = _lead_keys(a) & _lead_keys(b)
    return any(_subject_key(key) for key in shared)


def _within(a, b, hours=MERGE_WINDOW_HOURS):
    da, db = _parse(a.get('published_at')), _parse(b.get('published_at'))
    if not da or not db:
        return False
    return abs((da - db).total_seconds()) <= hours * 3600


def _pick_persona(rows):
    """One of the three seeds. The post's subject picks, not a new voice."""
    blob = '\n'.join(_blob(r) for r in rows)
    scores = {
        'trading': len(_PERSONA_TRADING.findall(blob)),
        'industry': len(_PERSONA_INDUSTRY.findall(blob)),
        'macro': len(_PERSONA_MACRO.findall(blob)),
    }
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        # A tape call with tickers is the trading voice. A long industry
        # essay with no macro word is the industry voice. Everything else
        # that survived classification is a market reading.
        if any(r.get('entities') for r in rows) and max(len(_blob(r)) for r in rows) < 400:
            return 'trading'
        if max(len(_blob(r)) for r in rows) > 800:
            return 'industry'
        return 'macro'
    return best


def classify_row(row, window):
    """REWRITE, MERGE, or SKIP for one subscribed item.

    MERGE requires another approved source, in the recent window, on the
    same subject, that itself has a judgment. Two relays of one headline
    are not a merge. A short judgment still rewrites. Length is not the test.
    """
    text = _body(_blob(row))
    author = row.get('author') or row.get('source_id')
    if _AD.search(text) and not _has_judgment(text):
        return {'action': 'SKIP', 'reason': '广告或导流', 'persona': None, 'peers': []}
    if _LIFE.search(text) and not _has_judgment(text):
        return {'action': 'SKIP', 'reason': '生活帖，没有市场判断', 'persona': None, 'peers': []}
    compact = re.sub(r'\s+', '', text)
    # A one-line tape blip is thin. A one-sentence judgment is not.
    if len(compact) < 24 or (len(compact) < 36 and not _has_judgment(text)):
        return {'action': 'SKIP', 'reason': '信息量太低', 'persona': None, 'peers': []}
    if _is_relay(text):
        return {'action': 'SKIP', 'reason': '纯转发或标题复读，没有自己的判断', 'persona': None, 'peers': []}
    if not _has_judgment(text):
        return {'action': 'SKIP', 'reason': '没有判断，只是复述', 'persona': None, 'peers': []}
    peers = []
    for other in window:
        if other.get('id') == row.get('id'):
            continue
        if (other.get('author') or other.get('source_id')) == author:
            continue
        if not _within(row, other):
            continue
        if not _same_subject(row, other):
            continue
        other_text = _blob(other)
        if not _has_judgment(other_text) or _is_relay(other_text):
            continue
        peers.append(other)
        if len(peers) >= 4:
            break
    persona = _pick_persona([row] + peers)
    if peers:
        names = []
        for peer in peers:
            name = peer.get('author') or peer.get('source_id')
            if name not in names:
                names.append(name)
        return {
            'action': 'MERGE',
            'reason': '最近窗口里还有 ' + '、'.join(names) + ' 在讲同一件事',
            'persona': persona,
            'peers': peers,
        }
    return {
        'action': 'REWRITE',
        'reason': '这一条本身已经有可以重组的判断',
        'persona': persona,
        'peers': [],
    }


def source_persona(source_id):
    """Coverage label for a subscription. Not the classifier's pick."""
    if not source_id:
        return None
    if source_id in FEED_PERSONA:
        return FEED_PERSONA[source_id]
    handle = source_id[2:] if source_id.startswith('x_') else source_id
    return HANDLE_PERSONA.get(handle)


def subscription_ids():
    """Source ids this file polls. One author with two channels counts twice."""
    return ['x_' + handle for handle in PRIORITY_HANDLES] + [row['id'] for row in PRIORITY_FEEDS]


def classify_latest(n=20, rows=None, per_source=2, hours=24, now=None):
    """Label one balanced round. Does not call a model.

    `n` remains so older callers still cap the round. The selection itself
    is per source, not "the newest n in the whole corpus".
    """
    rows = connected_rows(rows)
    newest = intake(rows, per_source=per_source, hours=hours, now=now)[:n]
    labeled = []
    for row in newest:
        decision = classify_row(row, rows)
        labeled.append({
            'id': row.get('id'),
            'source': row.get('source_id'),
            'author': row.get('author'),
            'published_at': row.get('published_at'),
            'url': row.get('url'),
            'title': row.get('title') or '',
            'text': row.get('text') or '',
            'action': decision['action'],
            'reason': decision['reason'],
            'persona': decision['persona'],
            'coverage': source_persona(row.get('source_id')),
            'peers': [
                {
                    'source': p.get('source_id'),
                    'author': p.get('author'),
                    'url': p.get('url'),
                    'text': p.get('text') or '',
                    'title': p.get('title') or '',
                }
                for p in decision['peers']
            ],
        })
    return labeled


def cited_fact_queries(text):
    """Concrete figures a post cites, for a later news check.

    News is not the writing material. A number inside a judgment is the
    only thing worth looking up. This returns the spans. It does not fetch.
    """
    blob = text or ''
    spans = []
    for cre in (
        re.compile(r'\$?\d+(?:\.\d+)?\s*(?:亿|万|billion|million|bn|mn)', re.I),
        re.compile(r'\d+(?:\.\d+)?%'),
        re.compile(r'\d+(?:\.\d+)?\s*(?:枚|bps|个基点)'),
    ):
        for m in cre.finditer(blob):
            span = m.group(0).strip()
            if span and span not in spans:
                spans.append(span)
    return spans[:6]
