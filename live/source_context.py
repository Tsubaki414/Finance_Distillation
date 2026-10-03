"""Account-scoped official captures, never post candidates or verified facts.

Discovery is bounded to configured publishers. Only exact links already cited by
an account's candidate can be attached as context. Capturing a publisher page is
not a factual-preservation/current-validity decision.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, urljoin, parse_qsl, urlencode
from urllib.request import Request, build_opener
import hashlib
import json
import re
import sqlite3
import xml.etree.ElementTree as ET

UTC = timezone.utc


def _time(value=None):
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            result = parsedate_to_datetime(str(value))
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def canonical_url(url):
    p = urlsplit(str(url))
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in {'fbclid', 'gclid'}]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), urlencode(query), ''))


def is_context_source(source_id, config=None):
    if str(source_id).startswith('primary_'):
        return True
    if config is None:
        from live.account_sources import registry
        config = registry().get(source_id, {})
    return config.get('content_role') == 'context_only'


def _allowed(url, hosts):
    p = urlsplit(url)
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443) or p.hostname not in hosts:
        raise ValueError('Official URL outside configured HTTPS publisher hosts')


def fetch_official(url, allowed_hosts, max_bytes=2_000_000):
    """Public XML/HTML only; validate every redirect and deny private addresses."""
    from live.source_recovery import NoRedirect, validate_url
    opener = build_opener(NoRedirect)
    for _ in range(4):
        validate_url(url, allowed_hosts)
        try:
            response = opener.open(Request(url, headers={'User-Agent': 'ContentLocalization/1.0 public-source-reader'}), timeout=25)
        except Exception as exc:
            if getattr(exc, 'code', 0) in (301, 302, 303, 307, 308):
                url = urljoin(url, exc.headers['Location'])
                continue
            raise
        with response:
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise ValueError('Official response exceeds bounded capture limit')
            kind = response.headers.get('Content-Type', '')
            if not any(k in kind for k in ('xml', 'html', 'text/plain')):
                raise ValueError('Official PDF/media requires a supplied extraction')
            return {'url': url, 'raw': raw.decode('utf-8', errors='replace'),
                    'content_type': kind, 'fetched_at': _time().isoformat()}
    raise ValueError('Too many official redirects')


def _capture(document, directory, requested_url):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {**document, 'requested_url': requested_url,
               'raw_hash': hashlib.sha256(document['raw'].encode()).hexdigest()}
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    path = directory / (hashlib.sha256(serialized.encode()).hexdigest() + '.json')
    if not path.exists():
        with path.open('x') as stream:
            stream.write(serialized)
    return str(path), payload['raw_hash']


def _body(document, config, spec):
    from bs4 import BeautifulSoup
    from live.source_recovery import extract_page
    soup = BeautifulSoup(document['raw'], 'html.parser')
    # Publisher selectors are grounded in captured HTML; no guessed semantic
    # boundaries and no reconstruction from a feed's summary.
    selector = config.get('body_selector')
    root = soup.select_one(selector) if selector else None
    if selector and root is None:
        raise ValueError('Configured official article body missing')
    extracted = extract_page({**document, 'raw': '<article>' + str(root) + '</article>'} if root else document)
    date = soup.select_one('meta[property="article:published_time"],meta[name="date"],time[datetime]')
    stamp = spec.get('published_at') or (date.get('content') or date.get('datetime') if date else None)
    try:
        stamp = _time(stamp).isoformat() if stamp else None
    except (ValueError, TypeError, OverflowError):
        stamp = None
    title = soup.find('h1') or soup.find('title')
    return {**extracted, 'original_text': extracted['text'], 'published_at': stamp,
            'title': spec.get('title') or (title.get_text(' ', strip=True) if title else ''),
            'publication_date_basis': 'feed_metadata' if spec.get('published_at') else 'publisher_metadata' if stamp else 'missing'}


def collect_official(account_id, source_id, config, prior, as_of, limit, capture_root, fetcher=None):
    """Return context rows + bounded checkpoint; document failures stay retryable."""
    from bs4 import BeautifulSoup
    fetcher = fetcher or fetch_official
    moment = _time(as_of)
    hosts = set(config.get('allowed_hosts') or [])
    if not hosts:
        raise ValueError('Official publisher hosts not configured')
    directory = Path(capture_root) / account_id / source_id / 'official'
    index_url = config.get('feed_url') or config.get('index_url')
    if not index_url:
        raise ValueError('Official discovery endpoint not configured')
    _allowed(index_url, hosts)
    index = fetcher(index_url, hosts)
    _allowed(index['url'], hosts)
    index_ref, _ = _capture(index, directory, index_url)
    specs = []
    if config.get('feed_url'):
        tree = ET.fromstring(index['raw'])
        items = tree.findall('.//item') or tree.findall('.//{http://www.w3.org/2005/Atom}entry')
        for item in items[:200]:
            values = {node.tag.rsplit('}', 1)[-1]: node for node in item}
            link = values.get('link')
            url = ((link.text or '').strip() or link.get('href')) if link is not None else None
            if url:
                specs.append({'url': urljoin(index['url'], url),
                              'title': values['title'].text if 'title' in values else '',
                              'published_at': next((values[k].text for k in ('pubDate', 'published', 'updated') if k in values), None)})
    else:
        patterns = config.get('document_path_patterns') or []
        for link in BeautifulSoup(index['raw'], 'html.parser').find_all('a', href=True):
            url = urljoin(index['url'], link['href'])
            if any(re.fullmatch(pattern, urlsplit(url).path) for pattern in patterns):
                specs.append({'url': url, 'title': link.get_text(' ', strip=True)})
        if not specs:
            raise ValueError('Official index has no configured release links')
    by_url = {}
    outside = 0
    for spec in specs:
        try:
            _allowed(spec['url'], hosts)
        except ValueError:
            outside += 1
            continue
        spec['index_signature'] = hashlib.sha256(json.dumps(
            [spec.get('published_at'), spec.get('title')], ensure_ascii=False).encode()).hexdigest()
        by_url.setdefault(canonical_url(spec['url']), spec)
    # Only the live discovery window stays in the checkpoint; the context store
    # owns persistent historical revisions. New entries precede scheduled refresh.
    seen = {key: value for key, value in (prior.get('official_seen') or {}).items() if key in by_url}
    refresh = timedelta(hours=config.get('context_refresh_hours', 24))
    pending = [(key, spec) for key, spec in by_url.items()
               if key not in seen or seen[key].get('index_signature') != spec['index_signature']
               or moment - _time(seen[key]['checked_at']) >= refresh]
    pending.sort(key=lambda pair: pair[0] in seen)
    cap = min(limit, int(config.get('max_documents_per_poll', 3)))
    rows, failures, duplicates = [], [], 0
    for key, spec in pending[:cap]:
        try:
            doc = fetcher(spec['url'], hosts)
            _allowed(doc['url'], hosts)
            ref, raw_hash = _capture(doc, directory, spec['url'])
            body = _body(doc, config, spec)
            body.pop('text', None)  # Do not send the same complete body twice.
            body_hash = hashlib.sha256(body['original_text'].encode()).hexdigest()
            duplicates += int(seen.get(key, {}).get('body_hash') == body_hash)
            rows.append({**body, 'account_id': account_id, 'source_id': source_id,
                         'url': doc['url'], 'requested_url': spec['url'], 'source_language': config.get('source_language', 'en'),
                         'fetched_at': doc.get('fetched_at') or moment.isoformat(),
                         'raw_import_ref': ref, 'raw_import_hash': raw_hash, 'index_capture_ref': index_ref,
                         'source_hash': body_hash, 'verification_status': 'captured_not_fact_verified',
                         'content_role': 'context_only', 'coverage': 'captured release body; linked files/media not read'})
            seen[key] = {'checked_at': moment.isoformat(), 'body_hash': body_hash,
                         'index_signature': spec['index_signature']}
        except Exception as exc:
            failures.append({'url': spec['url'], 'error': type(exc).__name__, 'retryable': True})
    cursor = {**prior, 'account_id': account_id, 'source_id': source_id,
              'checked_at': moment.isoformat(), 'official_seen': seen,
              'last_seen': max((r['published_at'] for r in rows if r.get('published_at')), default=prior.get('last_seen'))}
    remaining = max(0, len(pending) - cap)
    return rows, cursor, not failures and remaining == 0, {
        'status': 'context_only', 'context_only': True, 'checked': True,
        'adapter': 'official', 'capture_ref': index_ref, 'source_rows': len(by_url),
        'context_captured': len(rows), 'new_items': 0, 'duplicate_skipped': duplicates,
        'backlog': remaining, 'failures': failures, 'outside_publisher_skipped': outside,
        'refresh_hours': refresh.total_seconds() / 3600,
        'coverage': 'bounded current discovery window; metadata changes refresh immediately, other bodies refresh periodically'}


class ContextStore:
    def __init__(self, store_root, *, catalog=None, universe_loader=None):
        self.root = Path(store_root)
        self.path = self.root / 'source_context.sqlite3'
        self.catalog, self.universe_loader = catalog, universe_loader

    def _scope(self, account_id, source_id=None):
        from live.account_sources import registry, universe
        own = (self.universe_loader or universe)(account_id)
        catalog = self.catalog if self.catalog is not None else registry()
        allowed = {row['source_id']: catalog.get(row['source_id'], {}) for row in own['subscriptions']
                   if row.get('enabled') and row.get('role') not in {'REJECT', 'WATCHLIST'}
                   and is_context_source(row['source_id'], catalog.get(row['source_id'], {}))}
        if source_id is not None and source_id not in allowed:
            raise ValueError('Official context source outside account subscription universe')
        return allowed

    def _connect(self):
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('''CREATE TABLE IF NOT EXISTS captures (
            account_id TEXT NOT NULL, source_id TEXT NOT NULL, url TEXT NOT NULL,
            body_hash TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            payload TEXT NOT NULL, PRIMARY KEY (account_id, source_id, url, body_hash))''')
        db.execute('''CREATE TABLE IF NOT EXISTS observations (
            account_id TEXT NOT NULL, source_id TEXT NOT NULL, url TEXT NOT NULL,
            body_hash TEXT NOT NULL, observed_at TEXT NOT NULL, metadata TEXT NOT NULL,
            PRIMARY KEY (account_id, source_id, url, body_hash, observed_at))''')
        # Preserve known historical checkpoints when opening a pre-observation
        # store. We cannot invent intermediate capture times that were not saved.
        db.execute('''INSERT OR IGNORE INTO observations
            SELECT account_id,source_id,url,body_hash,first_seen,'{}' FROM captures''')
        return db

    def record(self, account_id, source_id, rows, as_of=None):
        config = self._scope(account_id, source_id)[source_id]
        moment = _time(as_of).isoformat()
        counts = {'new': 0, 'duplicate': 0, 'incomplete': 0}
        with closing(self._connect()) as db, db:
            for row in rows:
                if row.get('account_id', account_id) != account_id or row.get('source_id') != source_id:
                    raise ValueError('Official context identity/scope mismatch')
                _allowed(row['url'], set(config.get('allowed_hosts') or []))
                if row.get('requested_url'):
                    _allowed(row['requested_url'], set(config.get('allowed_hosts') or []))
                body = row.get('original_text', '')
                if not body.strip():
                    raise ValueError('Empty official context body')
                body_hash = hashlib.sha256(body.encode()).hexdigest()
                if row.get('source_hash', body_hash) != body_hash:
                    raise ValueError('Official context body hash mismatch')
                payload = {**row, 'account_id': account_id, 'source_id': source_id,
                           'source_hash': body_hash, 'content_role': 'context_only',
                           'verification_status': 'captured_not_fact_verified'}
                payload.pop('verified', None)
                payload.pop('text', None)
                key = (account_id, source_id, canonical_url(row['url']), body_hash)
                prior = db.execute('SELECT 1 FROM captures WHERE account_id=? AND source_id=? AND url=? AND body_hash=?', key).fetchone()
                if prior:
                    db.execute('UPDATE captures SET last_seen=? WHERE account_id=? AND source_id=? AND url=? AND body_hash=?', (moment, *key))
                    counts['duplicate'] += 1
                else:
                    db.execute('INSERT INTO captures VALUES (?,?,?,?,?,?,?)', (*key, moment, moment, json.dumps(payload, ensure_ascii=False)))
                    counts['new'] += 1
                observed = max(_time(moment), _time(row['fetched_at'])) if row.get('fetched_at') else _time(moment)
                metadata = {k: v for k, v in payload.items() if k not in {'original_text', 'source_hash'}}
                db.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)',
                           (*key, observed.isoformat(), json.dumps(metadata, ensure_ascii=False)))
                counts['incomplete'] += int(row.get('content_complete') is not True)
        return counts

    def references(self, account_id, candidate_source, as_of=None):
        allowed = self._scope(account_id)
        if not self.path.exists():
            return []
        moment = _time(as_of)
        links = []
        for value in candidate_source.get('external_links') or []:
            links.append(value.get('url') or value.get('href') if isinstance(value, dict) else value)
        links.extend(re.findall(r'https://[^\s<>\[\]"\u3000]+', candidate_source.get('original_text', candidate_source.get('text', ''))))
        wanted = {canonical_url(str(link).rstrip('.,;!?)。，；）')) for link in links if link}
        if not wanted:
            return []
        result = {}
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            has_observations = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='observations'").fetchone()
            query = '''SELECT c.source_id,c.url,o.observed_at,c.payload,o.metadata
                FROM observations o JOIN captures c
                USING (account_id,source_id,url,body_hash)
                WHERE c.account_id=? ORDER BY o.observed_at''' if has_observations else (
                "SELECT source_id,url,first_seen,payload,'{}' FROM captures WHERE account_id=? ORDER BY first_seen")
            rows = db.execute(query, (account_id,))
            for sid, url, observed_at, serialized, metadata in rows:
                if sid not in allowed or _time(observed_at) > moment:
                    continue
                row = {**json.loads(serialized), **json.loads(metadata)}
                if not ({url, canonical_url(row.get('requested_url') or row['url'])} & wanted):
                    continue
                if row.get('fetched_at') and _time(row['fetched_at']) > moment:
                    continue
                if row.get('published_at') and _time(row['published_at']) > moment:
                    continue
                result[(sid, url)] = {**row, 'relationship': 'exact_url_cited_by_candidate',
                                      'observed_at': observed_at,
                                      'verification_status': 'captured_not_fact_verified'}
        return list(result.values())

    def status(self, account_id):
        allowed = self._scope(account_id)
        rows = []
        if self.path.exists():
            with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                for sid, count, latest in db.execute('SELECT source_id,COUNT(*),MAX(last_seen) FROM captures WHERE account_id=? GROUP BY source_id', (account_id,)):
                    if sid in allowed:
                        rows.append({'source_id': sid, 'revision_count': count, 'last_seen': latest})
        return {'account_id': account_id, 'sources': rows, 'verification_status': 'captured_not_fact_verified'}
