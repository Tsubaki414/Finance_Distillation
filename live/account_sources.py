"""Account subscriptions precede selection. Shared storage never broadcasts events."""
from __future__ import annotations
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
import json
import re
import uuid
import fcntl
from datetime import date

from live.account_intelligence import ROOT, Store, account, require, time, now, digest, copy_risks
from live.distillation_source import source_record

CONFIG = ROOT / 'live/account_source_universes.json'
ROLES = {'CORE', 'SECONDARY', 'EVENT_ONLY', 'RESEARCH_ONLY', 'WATCHLIST', 'REJECT'}
PRIMARY = {'primary_bls': 'bls.gov', 'primary_bea': 'bea.gov', 'primary_fed': 'federalreserve.gov',
           'primary_treasury': 'treasury.gov', 'primary_nvidia': 'investor.nvidia.com',
           'primary_amd': 'ir.amd.com'}


def universes():
    config = json.loads(CONFIG.read_text())
    return [{**a, 'version': config['version'], 'universe_version': digest([config['version'], a])}
            for a in config['accounts']]


def universe(account_id):
    require(account(account_id).get('enabled') is True, 'Account inactive in the source desk')
    rows = [u for u in universes() if u['account_id'] == account_id]
    require(len(rows) == 1, 'Account has no confirmed source universe')
    return rows[0]


def registry():
    return {r['id']: r for r in json.loads((ROOT / 'live/source_registry.json').read_text())['sources']}


def _feed_hosts(r):
    """Feed host plus explicitly listed article hosts (e.g. rss.odaily.news links to www.odaily.news)."""
    return {urlparse(r['feed_url']).hostname, *(r.get('link_hosts') or [])}


def source_key(source):
    """Canonical publisher identity; an arbitrary source_id cannot impersonate Morris."""
    claimed = source.get('source_id')
    handle = str(source.get('author_handle') or source.get('author_name') or source.get('author') or '').lstrip('@').lower()
    host = (urlparse(source.get('url') or '').hostname or '').lower()
    path_parts = urlparse(source.get('url') or '').path.strip('/').split('/')
    if host in ('x.com', 'twitter.com', 'www.x.com') and len(path_parts) >= 3 and path_parts[1] == 'status' and path_parts[0] != 'i':
        require(path_parts[0].lower() == handle, 'X URL author/declared author mismatch')
    if claimed == 'x_Morris_LT' or handle == 'morris_lt':
        require(handle == 'morris_lt' and host in ('x.com', 'twitter.com', 'www.x.com'), 'Morris author/URL identity mismatch')
        return 'x_Morris_LT'
    for sid, domain in PRIMARY.items():
        if host == domain or host.endswith('.' + domain):
            require(not claimed or claimed == sid or str(claimed).startswith('source-'), 'Primary publisher/source_id mismatch')
            return sid
    sources = registry()
    if claimed in sources:
        r = sources[claimed]
        if r.get('handle'):
            require(handle == r['handle'].lower() and host in ('x.com', 'twitter.com', 'www.x.com'), 'X author/source_id mismatch')
        elif r.get('feed_url'):
            require(host in _feed_hosts(r), 'Publisher/source_id mismatch')
        return claimed
    # Existing captures may predate source_id. Domain/handle joins are exact.
    for sid, r in sources.items():
        if r.get('handle') and handle == r['handle'].lower() and host in ('x.com', 'twitter.com'):
            return sid
        if r.get('feed_url') and host in _feed_hosts(r):
            return sid
    return None


def admission(account_id, source):
    u = universe(account_id)
    sid = source_key(source)
    sub = next((s for s in u['subscriptions'] if s['source_id'] == sid and s.get('enabled')), None)
    if not sub:
        return {'admitted': False, 'reason': 'Source is outside this account subscription universe', 'source_id': sid}
    require(sub['role'] in ROLES, 'Invalid source role')
    from live.source_context import is_context_source
    if is_context_source(sid):
        return {'admitted': False, 'reason': 'Official context does not create content candidates', 'source_id': sid}
    if sub['role'] in ('RESEARCH_ONLY', 'WATCHLIST', 'REJECT'):
        return {'admitted': False, 'reason': 'Source role does not create content candidates', 'source_id': sid}
    charter = account(account_id)
    if source.get('source_language') == charter['language'] and charter.get('allow_same_language') is not True:
        # P0-1: same-language material never enters the translate/edit chain. It may
        # return only as an attributed view_relay post type (master plan 4.3).
        # Accounts with allow_same_language (crypto pilots, decision 2026-10-07) take it unattributed.
        return {'admitted': False, 'code': 'same_language', 'source_id': sid,
                'reason': 'Same-language source is isolated until the attributed view_relay post type exists'}
    text = (source.get('title') or '') + '\n' + source.get('original_text', source.get('text', ''))
    terms = sub.get('topic_scope', [])
    matches = [term for term in terms if re.search(re.escape(term), text, re.I)]
    if sub.get('candidate_policy') in ('topic_match', 'event_match') and not matches:
        return {'admitted': False, 'reason': 'No subscription topic trigger', 'source_id': sid}
    if account_id == 'en_morris_archive' and source.get('source_language') != 'zh':
        return {'admitted': False, 'reason': 'Morris archive takes Chinese historical originals', 'source_id': sid}
    return {'admitted': True, 'source_id': sid, 'subscription': sub,
            'subscription_ref': account_id + ':' + sub['id'], 'universe_version': u['universe_version'],
            'matched_topics': matches, 'reason': 'Subscribed source' if not terms else 'Subscription topic match (editorial suitability still pending)'}


def _date(value):
    if not value:
        return None
    try:
        return time(value).isoformat()
    except ValueError:
        return parsedate_to_datetime(value).isoformat()


def ingest(store, account_id, row, *, event_id=None, fixture_id=None, batch_id='intake'):
    """An explicit account import; no loop over accounts, no model calls."""
    raw = {**row, 'published_at': _date(row.get('published_at')),
           'fetched_at': _date(row.get('fetched_at') or row.get('snapshot_at'))}
    # Older Morris captures store missing-media requirements as plain strings.
    # Preserve their blocking meaning as annotations rather than crashing or
    # silently treating unread visuals as optional.
    raw['media_dependencies'] = [d if isinstance(d, dict) else {
        'kind': 'legacy_context_requirement', 'required': True,
        'status': 'required_missing', 'reason': str(d)} for d in (raw.get('media_dependencies') or [])]
    source = source_record(raw)
    verdict = admission(account_id, source)
    if not verdict['admitted']:
        return verdict
    source = source_record({**source, 'source_id': verdict['source_id']})
    source['completeness_basis'] = row.get('completeness_basis') or row.get('context_status') or source['extraction_status']
    source['raw_import_ref'] = row.get('raw_import_ref') or row.get('raw_snapshot') or row.get('url')
    if row.get('context_status'):
        source['context_status'] = row['context_status']
    semantic_source = {k: source.get(k) for k in ('source_id', 'url', 'author_name', 'author_id', 'author_handle',
        'source_hash', 'source_language', 'title', 'published_at', 'platform', 'content_complete', 'completeness_basis',
        'media_dependencies', 'quoted_post', 'reply_to', 'thread_id', 'context_items', 'recovery',
        'context_status', 'entity_glossary', 'extraction_status', 'truncated',
        'event_id', 'event_key', 'canonical_event_id')}
    identity = [account_id, verdict['universe_version'], semantic_source, bool(source.get('fetched_at')), event_id]
    key = 'inbox-' + digest(identity)[:24]
    prior = next((r for r in store.rows('inbox') if r['id'] == key), None)
    if prior:
        return {'admitted': True, 'candidate': prior, 'duplicate': True}
    stored = store.source(source)
    gaps = []
    if not source['content_complete']:
        gaps.append('Original text completeness unverified')
    if any(d.get('required') is True or d.get('indispensable') is True or d.get('status') in ('required_missing', 'missing_required', 'unresolved_required') or (d.get('required') is not False and d.get('status') != 'uncertain_dependency') for d in source['media_dependencies']) or any(d.get('required') is True for d in (source.get('recovery') or {}).get('unresolved', [])):
        gaps.append('Required media/thread/context unresolved')
    if not source.get('published_at') or not source.get('fetched_at'):
        gaps.append('Publication/capture date missing')
    if source.get('published_at') and time(source['published_at']) > time(now()):
        gaps.append('Publication timestamp is in the future')
    event = store.get('events', event_id) if event_id else None
    if event:
        require(any(store.get('sources', sid)['source_hash'] == source['source_hash'] for sid in event['source_ids']), 'Fixture source/event mismatch')
    value = {'id': key, 'recorded_at': now(), 'account_id': account_id, 'source_id': stored['id'],
             'canonical_source_id': verdict['source_id'], 'source_version': source['source_version'],
             'subscription_ref': verdict['subscription_ref'], 'universe_version': verdict['universe_version'],
             'admission': verdict, 'title': source['title'] or source['original_text'][:110],
             'status': 'needs_source' if gaps else 'pending_selection', 'blocking_gaps': gaps,
             'mode': event['mode'] if event else universe(account_id)['mode'],
             'event_id': event_id, 'fixture_id': fixture_id, 'batch_id': batch_id,
             'target_language': account(account_id)['language'], 'source_language': source['source_language']}
    return {'admitted': True, 'candidate': store.append('inbox', value), 'duplicate': False}


def valid_candidate(store, account_id, candidate_id):
    candidate = store.get('inbox', candidate_id)
    require(candidate['account_id'] == account_id, 'Candidate belongs to another account')
    source = store.get('sources', candidate['source_id'])
    verdict = admission(account_id, source)
    require(verdict['admitted'] and verdict['universe_version'] == candidate['universe_version'], 'Subscription changed; re-admit this source')
    require(verdict['source_id'] == candidate['canonical_source_id'], 'Source identity changed')
    return candidate, source


def inbox(store, account_id):
    universe(account_id)
    runs = [r for r in store.rows('runs') if r.get('pipeline') == 'account_source' and r['account_id'] == account_id]
    values = []
    for row in store.rows('inbox'):
        if row['account_id'] != account_id:
            continue
        related = [r for r in runs if r['inbox_candidate_id'] == row['id']]
        current = True
        try:
            valid_candidate(store, account_id, row['id'])
        except ValueError:
            current = False
        values.append({**row, 'current': current, 'status': related[-1]['status'] if related else row['status'],
                       'source': store.get('sources', row['source_id']),
                       'runs': [{'id': r['id'], 'status': r['status'], 'recorded_at': r['recorded_at'],
                                 'draft_count': len(r['candidates'])} for r in related]})
    return {'account': account(account_id), 'universe': universe(account_id), 'candidates': values,
            'runs': [{'id': r['id'], 'inbox_candidate_id': r['inbox_candidate_id'], 'status': r['status']} for r in runs]}


def _media_uncertainty(row):
    """A visual clue is not proof that every passage depends on the visual."""
    if row.get('media') and re.search(r'\b(?:chart|figure|graph|pictured|shown below)\b|见图|如下图|图中', row.get('original_text', row.get('text', '')), re.I):
        clue = {'kind': 'figure_context', 'required': None, 'status': 'uncertain_dependency',
                'selection_review_required': True,
                'reason': 'Unread referenced media; select only an independently complete text argument, never infer chart values'}
        # Preserve explicit indispensable dependencies; never downgrade them.
        row = {**row, 'media_dependencies': [*(row.get('media_dependencies') or []), clue]}
    return row


def _primary_document(spec, directory):
    """One supplied official URL, not automatic release discovery or fact verification."""
    from bs4 import BeautifulSoup
    from live.source_recovery import fetch_public, extract_page
    sid, url = spec['source_id'], spec['url']
    domain = PRIMARY[sid]
    allowed = set(registry().get(sid, {}).get('allowed_hosts') or {domain, 'www.' + domain})
    require(urlparse(url).scheme == 'https' and urlparse(url).hostname in allowed,
            'Official document URL outside the configured publisher hosts')
    document = fetch_public(url, allowed)
    capture = {**document, 'requested_url': url, 'source_id': sid, 'retrieval_mode': 'explicit_official_url',
               'document_hash': digest(document['raw'])}
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (digest(capture) + '.json')
    if not path.exists():
        with path.open('x') as fh:
            json.dump(capture, fh, ensure_ascii=False, indent=2)
    extracted = extract_page(document)
    soup = BeautifulSoup(document['raw'], 'html.parser')
    date_tag = soup.find('meta', attrs={'property': 'article:published_time'}) or soup.find('meta', attrs={'name': 'date'})
    publication = date_tag.get('content') if date_tag else spec.get('published_at')
    title_tag = soup.find('h1') or soup.find('title')
    return {**extracted, 'id': 'official-' + digest(capture)[:20], 'source_id': sid,
            'original_text': extracted['text'], 'author_name': sid.removeprefix('primary_').upper(),
            'title': title_tag.get_text(' ', strip=True) if title_tag else spec.get('title', ''),
            'source_type': 'official_document', 'platform': 'web', 'published_at': _date(publication),
            'raw_import_ref': str(path), 'raw_import_hash': capture['document_hash'],
            'context_items': [{'kind': 'official_capture', 'retrieval_mode': 'explicit_official_url',
                'publication_date_basis': 'publisher_metadata' if date_tag else 'supplied_input' if publication else 'missing',
                'verification_status': 'not_independently_fact_checked', 'raw_import_ref': str(path)}]}


def fetch_flash_json(config, limit, transport=None):
    """Account-scoped 7x24 flash list (WSCN JSON parser); global flashes.OUTLETS untouched."""
    from live.adapters import common, flashes
    from live.analysis_corpus import _row
    require(config.get('parser') == 'wscn', 'Unsupported flash_json parser')
    status, body = common.http_get(config['feed_url'], transport=transport)
    if status != 200:
        return [], f'http_{status}'
    rows = []
    for flash in flashes._parse_wscn(body):
        text = flash['text']
        if len(text) < flashes.MIN_CHARS or flashes._PROMO.search(text) or flash['published'] is None:
            continue
        title = flash.get('title') or (re.match(r'^【([^】]{4,80})】', text) or [None, text[:40]])[1]
        row = _row(config['id'], config['name'], flash['published'].isoformat(), title, text, flash['url'],
                   'crypto_flash', content_complete=True, extraction_status='flash_json',
                   author_name=config['name'], publisher_name=config['name'], no_reproduction=True)
        if row:
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows, None


def refresh(store, account_id, limit=3, *, source_ids=None, include_x=False, since=None, until=None,
            primary_documents=None, max_sources=3):
    """Bounded, explicitly invoked intake for one account's subscriptions. No fan-out,
    scheduler, generation, implicit X spend, or claim of a complete historical archive.
    """
    from live.analysis_corpus import fetch_feed
    u, catalog = universe(account_id), registry()
    eligible = {s['source_id']: s for s in u['subscriptions'] if s['enabled'] and s['role'] in ('CORE', 'SECONDARY', 'EVENT_ONLY')}
    require(type(limit) is int and 1 <= limit <= 12 and type(max_sources) is int and 1 <= max_sources <= 12,
            'Refresh limits must be between 1 and 12')
    require(source_ids is None or isinstance(source_ids, list) and all(isinstance(s, str) and s in eligible for s in source_ids),
            'Refresh source outside this account candidate subscriptions')
    selected = list(dict.fromkeys(source_ids)) if source_ids is not None else list(eligible)
    documents = primary_documents or []
    require(isinstance(documents, list) and len(documents) <= 12, 'Supply at most 12 explicit official documents')
    for spec in documents:
        require(isinstance(spec, dict) and spec.get('source_id') in selected and spec['source_id'] in PRIMARY,
                'Official document outside the selected account subscriptions')
        domain = PRIMARY[spec['source_id']]
        hosts = set(catalog.get(spec['source_id'], {}).get('allowed_hosts') or {domain, 'www.' + domain})
        require(urlparse(spec.get('url', '')).scheme == 'https' and urlparse(spec.get('url', '')).hostname in hosts,
                'Official document URL outside the configured publisher hosts')
    if since or until:
        require(bool(since and until), 'Supply both since and until dates for a bounded X window')
        require(date.fromisoformat(since) < date.fromisoformat(until) <= date.fromisoformat(now()[:10]), 'Invalid X date window')
    # Morris is a historical archive, not a latest-tweets poll disguised as history.
    if include_x and 'x_Morris_LT' in selected:
        require(bool(since and until), 'Morris refresh requires an explicit historical since/until window')
    results, notes, fetches = [], [], 0
    raw_directory = store.root.parent / 'source_captures' / account_id
    for sid in selected:
        config = catalog.get(sid, {})
        if sid.startswith('x_') and not config.get('handle'):
            config = {**config, 'handle': sid[2:]}
        if fetches >= max_sources:
            notes.append({'source_id': sid, 'status': 'refresh_fetch_limit_reached'})
            continue
        try:
            if config.get('adapter') == 'feed':
                fetches += 1
                rows, error = fetch_feed({'id': sid, 'author': config.get('name'), 'url': config['feed_url']}, limit=limit)
                if error:
                    notes.append({'source_id': sid, 'status': error})
            elif config.get('adapter') == 'flash_json':
                fetches += 1
                rows, error = fetch_flash_json({**config, 'id': sid}, limit)
                if error:
                    notes.append({'source_id': sid, 'status': error})
            elif config.get('handle') and include_x:
                from live.xsearch import search
                handle = config['handle'].lstrip('@')
                require(re.fullmatch(r'[A-Za-z0-9_]{1,50}', handle), 'Invalid subscribed X handle')
                query = 'from:' + handle + (f' since:{since} until:{until}' if since else '')
                fetches += 1
                capture = search(query, max_items=limit, raw_directory=raw_directory / 'x')
                notes.append({'source_id': sid, 'status': 'bounded_x_sample',
                              **{k: capture.get(k) for k in ('apify_run_id', 'apify_dataset_id', 'billed_usd', 'raw_snapshot')},
                              'archive_complete': False})
                rows = []
                for row in capture['rows'][:limit]:
                    if str(row.get('author_handle') or row.get('handle') or '').lower() != handle.lower():
                        notes.append({'source_id': sid, 'status': 'unexpected_search_author_rejected', 'post_id': row.get('post_id')})
                    else:
                        rows.append({**row, 'source_id': sid})
            elif sid in PRIMARY:
                specs = [s for s in documents if s['source_id'] == sid]
                if not specs:
                    notes.append({'source_id': sid, 'status': 'explicit_official_url_required',
                                  'reason': 'Manual refresh accepts exact URLs; the daily monitor discovers official releases as context'})
                rows = []
                for spec in specs[:limit]:
                    if fetches >= max_sources:
                        notes.append({'source_id': sid, 'status': 'refresh_fetch_limit_reached'})
                        break
                    fetches += 1
                    rows.append(_primary_document(spec, raw_directory / 'official'))
            else:
                notes.append({'source_id': sid, 'status': 'x_opt_in_required' if config.get('handle') else 'explicit_import_required'})
                rows = []
            for row in rows[:limit]:
                from live.source_context import ContextStore, is_context_source
                if is_context_source(sid, config):
                    counts = ContextStore(store.root).record(account_id, sid, [row], now())
                    results.append({'admitted': False, 'context_only': True, 'source_id': sid,
                                    'url': row['url'], 'raw_import_ref': row['raw_import_ref'],
                                    'context_recorded': counts})
                    continue
                results.append(ingest(store, account_id, _media_uncertainty(row), batch_id='bounded-refresh'))
        except Exception as exc:
            notes.append({'source_id': sid, 'status': 'refresh_failed', 'error_type': type(exc).__name__})
    return {'account_id': account_id, 'results': results, 'notes': notes, 'fetches': fetches,
            'max_fetches': max_sources, 'per_source_limit': limit, 'generation_calls': 0}


def current_evidence_records(store, values, as_of):
    """Resolve explicitly supplied checks against immutable captures; never fetch or
    promote a verification label into an independent/human check we did not do.
    """
    require(isinstance(values, list) and len(values) <= 20, 'Current evidence must be a bounded list (at most 20)')
    cutoff, seen, output = time(as_of), set(), []
    for item in values:
        require(isinstance(item, dict), 'Current evidence must contain structured records')
        eid = item.get('id')
        require(isinstance(eid, str) and eid.strip() and eid not in seen, 'Current evidence IDs must be unique and nonempty')
        seen.add(eid)
        source = store.get('sources', item.get('source_id'))
        quote = item.get('source_quote')
        require(isinstance(quote, str) and quote.strip() and quote in source['original_text'], 'Evidence source_quote must be an exact captured span')
        require(source.get('content_complete') is True, 'Evidence source completeness must be verified')
        require(urlparse(source.get('url') or '').scheme == 'https', 'Evidence source requires a provenance HTTPS URL')
        verification = item.get('verification')
        require(item.get('verification_status') == 'verified' and isinstance(verification, dict)
                and all(isinstance(verification.get(k), str) and verification[k].strip() for k in ('by', 'method', 'reason')),
                'Evidence needs an explicit verifier, method and reason; supplied checks are not independently verified')
        stamps = {k: time(v) for k, v in {'published_at': source.get('published_at'),
                  'fetched_at': source.get('fetched_at'), 'as_of': item.get('as_of'), 'verified_at': item.get('verified_at')}.items()}
        require(all(v <= cutoff for v in stamps.values()), 'Evidence timestamp is later than account as_of')
        require(stamps['published_at'] <= stamps['fetched_at'] <= stamps['verified_at']
                and stamps['published_at'] <= stamps['as_of'] <= stamps['verified_at'], 'Evidence verification/capture chronology invalid')
        output.append({'id': eid, 'source_id': source['id'], 'source_version': source.get('source_version'),
                       'source_hash': source['source_hash'], 'text': quote, 'source_quote': quote,
                       'url': source['url'], 'author_name': source.get('author_name'),
                       **{k: v.isoformat() for k, v in stamps.items()}, 'verification_status': 'verified',
                       'verification': {k: verification[k] for k in ('by', 'method', 'reason')},
                       'verification_origin': 'explicit_source_backed_input_not_independently_verified'})
    return output


class SourcePipeline:
    def __init__(self, store=None, client=None, adapter=None):
        self.store, self.client, self.adapter = store or Store(), client, adapter

    @property
    def generation_configuration(self):
        if self.adapter is not None or self.client is not None:
            return getattr(self.client, 'configuration', None)
        from live.content_stages import make_content_stages
        return make_content_stages(self.store.root.parent / 'adaptations').configuration

    def run(self, account_id, candidate_id, follow_up_of=None, *, current_evidence=None, monitor_context=None):
        require(isinstance(candidate_id, str) and re.fullmatch(r'[\w-]+', candidate_id), 'Invalid candidate id')
        universe(account_id)
        locks = self.store.root / 'candidate_locks'
        locks.mkdir(parents=True, exist_ok=True)
        # Shared by dashboard and monitor. Different candidates in the same
        # thread/event cannot race past the account-scoped duplicate check.
        with (locks / ('account-' + account_id + '.lock')).open('a') as account_lock, (locks / (candidate_id + '.lock')).open('a') as lock:
            fcntl.flock(account_lock, fcntl.LOCK_EX)
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return self._run(account_id, candidate_id, follow_up_of, current_evidence=current_evidence,
                                 monitor_context=monitor_context)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
                fcntl.flock(account_lock, fcntl.LOCK_UN)

    def _run(self, account_id, candidate_id, follow_up_of=None, *, current_evidence=None, monitor_context=None):
        candidate, source = valid_candidate(self.store, account_id, candidate_id)
        execution_repairs = []
        checkpoint = None
        previous = [r for r in self.store.rows('runs') if r.get('inbox_candidate_id') == candidate_id]
        if previous and not follow_up_of:
            require(current_evidence is None, 'New evidence requires an explicit follow-up of the prior run')
            return previous[-1]
        if not follow_up_of:
            from live.source_identity import duplicate_run
            prior = duplicate_run(self.store, account_id, source)
            if prior:
                return prior
        if follow_up_of:
            parent = self.store.get('runs', follow_up_of)
            require(parent['account_id'] == account_id, 'Follow-up account mismatch')
            originals = [self.store.get('sources', sid) for sid in parent['event']['source_ids']]
            require(any(s['source_hash'] == source['source_hash'] and s.get('url') == source.get('url')
                        and s.get('author_name') == source.get('author_name') for s in originals), 'Follow-up source identity mismatch')
            from live.account_source_adaptation import qa_checkpoint
            if qa_checkpoint(parent):
                checkpoint = parent
            if self.client is None:
                from live.content_stages import follow_up_repairs
                from live.account_source_adaptation import execution_failure
                adaptation = parent.get('source_adaptation') or {}
                execution_repairs = follow_up_repairs({**parent, 'source_adaptation': {
                    **adaptation, 'execution_failure': execution_failure(adaptation)}})
        if candidate.get('event_id'):
            event = self.store.get('events', candidate['event_id'])
        else:
            cutoff = ((monitor_context or {}).get('as_of')
                      if (monitor_context or {}).get('mode') == 'replay' else now())
            event_mode = (monitor_context or {}).get('mode')
            event_mode = 'replay' if event_mode == 'replay' else candidate['mode']
            event = self.store.event({'family': 'account-source-' + digest([account_id, source['source_id'], source.get('url')])[:24],
                'title': candidate['title'], 'mode': event_mode, 'occurred_at': min(source.get('published_at') or cutoff, cutoff),
                'as_of': cutoff, 'source_ids': [source['id']], 'evidence': [], 'blocking_gaps': candidate['blocking_gaps'],
                'coverage': 'Source-grounded adaptation; exact source is primary input, no inferred event commentary'})
        run = {'id': 'run-' + uuid.uuid4().hex, 'pipeline': 'account_source', 'recorded_at': now(),
               'account_id': account_id, 'target_language': account(account_id)['language'],
               'event': event, 'state': self.store.snapshot(account_id, event['as_of'] if event['mode'] == 'replay' else None), 'inbox_candidate_id': candidate_id,
               'universe_version': candidate['universe_version'], 'batch_id': candidate['batch_id'],
               'fixture_id': candidate['fixture_id'], 'follow_up_of': follow_up_of, 'candidates': [],
               'execution_repairs': execution_repairs,
               'status': 'started', 'human_status': 'pending', 'publishing_enabled': False}
        if monitor_context:
            run.update(monitor_cycle=monitor_context['cycle_id'], monitor_as_of=monitor_context['as_of'],
                       generation_origin='automatic_monitor', monitor_mode=monitor_context['mode'])
            revision_parent = monitor_context.get('source_revision_of')
            if revision_parent:
                original_run = self.store.get('runs', revision_parent)
                require(not follow_up_of and original_run['account_id'] == account_id
                        and not original_run.get('candidates'), 'Source revision cannot rewrite an existing draft')
                originals = [self.store.get('sources', sid) for sid in original_run['event']['source_ids']]
                require(any(s.get('url') == source.get('url') and s.get('author_name') == source.get('author_name')
                            and s.get('source_version') != source.get('source_version') for s in originals),
                        'Source revision identity unchanged or mismatched')
                run['source_revision_of'] = revision_parent
        try:
            context = {'as_of': event['as_of'], 'mode': event['mode'], 'state': run['state'],
                       'human_feedback': self.store.feedback_context(account_id, event['as_of'] if event['mode'] == 'replay' else now())}
            from live.source_context import ContextStore
            official = ContextStore(self.store.root).references(account_id, source, event['as_of'])
            if official:
                context['official_source_context'] = official
                run['official_source_context'] = official
            if current_evidence is not None:
                context['current_evidence'] = current_evidence_records(self.store, current_evidence, event['as_of'])
                run['current_evidence'] = context['current_evidence']
                run['current_evidence_hash'] = digest(context['current_evidence'])
            if checkpoint:
                require(current_evidence is None, 'QA-only recovery cannot change factual context')
                context = checkpoint['source_adaptation']['attempt']['account_context']
                run['execution_checkpoint'] = {'parent_run_id': checkpoint['id'], 'resume_stage': 'qa',
                    'body_hash': digest(checkpoint['source_adaptation']['final_draft']),
                    'upstream_regeneration_permitted': False}
            if candidate['blocking_gaps']:
                run.update(status='wait', decision={'action': 'wait', 'reason': '; '.join(candidate['blocking_gaps'])})
            else:
                from live.account_source_adaptation import adapt_source
                adapter = self.adapter or adapt_source
                extra = {'checkpoint': checkpoint} if checkpoint else {}
                result = adapter(source, account_id, self.store.root.parent / 'adaptations' / run['id'],
                    client=self.client, follow_up_of=follow_up_of,
                    account_context=context, execution_repairs=execution_repairs, **extra)
                run['source_adaptation'] = result
                run['prompt_version'] = result.get('pipeline_version')
                run['generation_protocol'] = result.get('generation_protocol')
                run['stage_configuration'] = result.get('stage_configuration')
                route = result.get('route') or {}
                draft = result.get('final_draft') or ''
                run['decision'] = {'action': 'speak' if draft else ('ignore' if result.get('status') == 'skipped' else 'wait'),
                                   'reason': route.get('reason') or result.get('draft_status') or result.get('status')}
                if draft:
                    from live.account_source_adaptation import execution_failed
                    risks = copy_risks(self.store, run, draft)
                    fidelity = result.get('machine_fidelity', {})
                    passed = result.get('draft_status') == 'draft_ready' and not risks
                    run['candidates'] = [{'id': run['id'] + '-c1', 'text': draft, 'human_status': 'pending',
                        'machine_fidelity_pass': passed, 'machine_qa': fidelity, 'deterministic_risks': risks,
                        'editorial_quality': 'human_review_pending', 'claim_links': [],
                        'selected_passages': (result.get('selection') or {}).get('passages', [])}]
                    run['status'] = ('execution_failed' if execution_failed({'source_adaptation': result})
                                     else 'candidates_ready' if passed else 'machine_hold')
                else:
                    run['status'] = 'execution_failed' if result.get('draft_status') == 'blocked' else run['decision']['action']
        except Exception as exc:
            run.update(status='execution_failed', error_type=type(exc).__name__)
            if isinstance(exc, ValueError):
                run['contract_error'] = str(exc)[:240]
        run['finished_at'] = now()
        self.store.append('runs', run)
        return run
