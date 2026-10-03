"""Bounded, account-scoped polling for the daily source monitor.

The caller owns the durable transaction: enqueue every returned item, then commit
``cursor``. Fetching never creates a draft, changes a subscription, or publishes.
Archive checkpoints contain identities, not offsets, so an appended/reordered
Morris corpus cannot replay consumed posts or hide newly imported older posts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import hashlib
import json
import re
import uuid

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
FETCH_CAP = 200
DEFAULT_ARCHIVES = (
    ROOT / 'runs/content_workbench_v1/morris/sources.json',
    ROOT / 'runs/content_batch_v2/source_selection/en_morris_archive/selected_sources.json',
)


class IntakeFailure(RuntimeError):
    def __init__(self, code, message=None, *, retryable=True):
        self.code, self.retryable = code, retryable
        super().__init__(message or code)


@dataclass
class FetchResult:
    items: list[dict]
    cursor: dict
    complete: bool
    diagnostics: dict = field(default_factory=dict)
    context_items: list[dict] = field(default_factory=list)


def utc(value=None):
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        parsed = parsedate_to_datetime(str(value))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def identity(row):
    """Stable source-item identity, shared across X URL spelling variants."""
    url = str(row.get('url') or '')
    parts = urlsplit(url)
    if (parts.hostname or '').lower() in {'x.com', 'twitter.com', 'www.x.com', 'www.twitter.com'}:
        match = re.search(r'/status/(\d+)', parts.path)
        if match:
            return 'x:' + match.group(1)
    if url:
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if not k.lower().startswith('utm_') and k.lower() not in {'fbclid', 'gclid'}]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip('/'),
                           urlencode(query), ''))
    if row.get('post_id'):
        return 'x:' + str(row['post_id'])
    text = row.get('original_text', row.get('text', ''))
    return 'body:' + hashlib.sha256(str(text).encode()).hexdigest()


def _load_archives(paths):
    found, malformed, by_id = 0, 0, {}
    for path in paths:
        path = Path(path)
        if not path.is_file():
            continue
        found += 1
        try:
            raw = ([json.loads(line) for line in path.read_text().splitlines() if line.strip()]
                   if path.suffix == '.jsonl' else json.loads(path.read_text()))
            values = raw if isinstance(raw, list) else raw.get('sources', raw.get('rows', []))
        except (ValueError, OSError, AttributeError) as exc:
            raise IntakeFailure('archive_parse_failed', type(exc).__name__) from exc
        for value in values:
            row = value.get('source', value.get('row', value)) if isinstance(value, dict) else {}
            handle = str(row.get('author_handle') or row.get('handle_at_collection') or
                         row.get('handle') or row.get('author_name') or '').lstrip('@').lower()
            if handle != 'morris_lt' or row.get('source_id') not in (None, 'x_Morris_LT'):
                malformed += 1
                continue
            if not str(row.get('original_text', row.get('text', ''))).strip():
                malformed += 1
                continue
            row = {**row, 'source_id': 'x_Morris_LT', 'author_handle': 'Morris_LT',
                   'original_text': row.get('original_text', row.get('text', '')),
                   'published_at': row.get('published_at') or row.get('created_at'),
                   'fetched_at': row.get('fetched_at') or row.get('collected_at'),
                   'raw_import_ref': row.get('raw_import_ref') or str(path),
                   'monitor_source_mode': 'historical_archive'}
            if not row.get('content_complete'):
                from live.archive_verification import verify_archive_row
                row = verify_archive_row(row)  # P0-3c
            key = identity(row)
            previous = by_id.get(key)
            # Later verified imports may improve completeness without changing the
            # identity that the monitor already consumed. Never prefer a teaser.
            if previous is None or row.get('content_complete') or not previous.get('content_complete'):
                by_id[key] = row
    if not found:
        raise IntakeFailure('archive_missing', 'No configured Morris historical corpus exists', retryable=False)
    return list(by_id.values()), {'archive_files': found, 'excluded_non_morris_or_empty': malformed,
                                 'archive_scope': 'saved historical corpus; not a complete Morris history'}


class Poller:
    def __init__(self, capture_root, archive_paths=None, allow_paid_x=False, *,
                 feed_fetcher=None, x_fetcher=None, max_age_hours=72,
                 x_reservation_usd=0.15, catalog=None, universe_loader=None,
                 recovery_fetcher=None, recover_bodies=True, body_retry_hours=6,
                 official_fetcher=None):
        self.capture_root = Path(capture_root)
        self.archive_paths = tuple(archive_paths) if archive_paths is not None else None
        self.allow_paid_x = allow_paid_x
        self.max_age_hours = max_age_hours
        self.x_reservation_usd = x_reservation_usd
        self.feed_fetcher, self.x_fetcher = feed_fetcher, x_fetcher
        self.catalog, self.universe_loader = catalog, universe_loader
        self.recovery_fetcher, self.recover_bodies = recovery_fetcher, recover_bodies
        self.body_retry_hours = body_retry_hours
        self.official_fetcher = official_fetcher

    def fetch(self, account_id, subscription, cursor=None, *, as_of=None, limit=20):
        from live.account_sources import universe, registry
        if type(limit) is not int or not 1 <= limit <= FETCH_CAP:
            raise ValueError('Per-source poll limit must be between 1 and 200')
        moment, prior = utc(as_of), dict(cursor or {})
        sid = subscription['source_id']
        own = (self.universe_loader or universe)(account_id)
        subscribed = next((s for s in own['subscriptions'] if s['source_id'] == sid and s.get('enabled')), None)
        if not subscribed:
            raise IntakeFailure('source_outside_account', retryable=False)
        if prior.get('account_id', account_id) != account_id or prior.get('source_id', sid) != sid:
            raise IntakeFailure('cursor_scope_mismatch', retryable=False)
        bound = {**prior, 'account_id': account_id, 'source_id': sid, 'checked_at': moment.isoformat()}
        config = (self.catalog if self.catalog is not None else registry()).get(sid, {})
        from live.source_context import is_context_source, collect_official
        if is_context_source(sid, config) and subscribed['role'] not in {'WATCHLIST', 'REJECT'}:
            if config.get('adapter') != 'official':
                return FetchResult([], bound, False, {'status': 'context_only', 'context_only': True,
                    'source_id': sid, 'reason': 'Official context adapter not configured',
                    'checked': False, 'duplicate_skipped': 0})
            try:
                rows, checkpoint, complete, diagnostics = collect_official(account_id, sid, config,
                    bound, moment, limit, self.capture_root, self.official_fetcher)
            except Exception as exc:
                raise IntakeFailure('official_fetch_failed', type(exc).__name__) from exc
            return FetchResult([], checkpoint, complete, diagnostics, rows)
        if subscribed['role'] in {'RESEARCH_ONLY', 'WATCHLIST', 'REJECT'}:
            return FetchResult([], bound, True, {'status': 'context_only', 'source_id': sid,
                                'reason': 'Shared primary/research sources do not create post candidates',
                                'checked': False, 'duplicate_skipped': 0})
        if sid == 'x_Morris_LT':
            if account_id != 'en_morris_archive':
                raise IntakeFailure('archive_account_mismatch', retryable=False)
            paths = self.archive_paths
            if paths is None:
                paths = [ROOT / path for path in config.get('archive_paths', [])] or list(DEFAULT_ARCHIVES)
                imports = ROOT / config['archive_import_dir'] if config.get('archive_import_dir') else None
                if imports and imports.is_dir():
                    paths.extend(sorted(path for path in imports.iterdir()
                                        if path.is_file() and path.suffix in {'.json', '.jsonl'}))
            rows, info = _load_archives(paths)
            info['coverage'] = config.get('coverage', 'bounded_saved_history_not_complete')
            return self._page(rows, bound, moment, limit, archive=True, diagnostics=info)
        if config.get('adapter') == 'feed':
            from live.analysis_corpus import fetch_feed
            try:
                rows, error = (self.feed_fetcher or fetch_feed)(
                    {'id': sid, 'author': config.get('name'), 'url': config['feed_url']}, limit=FETCH_CAP)
            except Exception as exc:
                raise IntakeFailure('feed_fetch_failed', type(exc).__name__) from exc
            if error:
                raise IntakeFailure('feed_' + str(error))
            capture = self._snapshot(account_id, sid, {'fetched_at': moment.isoformat(),
                'feed_url': config['feed_url'], 'rows': rows, 'capture_kind': 'normalized_feed_rows'})
            rows = [{**row, 'source_id': sid, 'raw_import_ref': str(capture) + f'#rows/{i}'}
                    for i, row in enumerate(rows)]
            result = self._page(rows, bound, moment, limit, diagnostics={
                'adapter': 'feed', 'capture_ref': str(capture), 'provider_limit': FETCH_CAP,
                'coverage': 'current RSS/Atom window; not a complete publication archive',
                'retrieval_saturated': len(rows) >= FETCH_CAP})
            self._recover_bodies(result, account_id, sid, config, moment)
            return result
        if config.get('handle') or sid.startswith('x_'):
            return self._x(account_id, sid, config, bound, moment, limit)
        raise IntakeFailure('unsupported_source_adapter', sid, retryable=False)

    def _snapshot(self, account_id, sid, payload):
        directory = self.capture_root / account_id / sid
        directory.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        path = directory / (hashlib.sha256(raw.encode()).hexdigest() + '.json')
        if not path.exists():
            with path.open('x') as stream:
                stream.write(raw)
        return path

    def _page(self, rows, bound, moment, limit, *, archive=False, diagnostics=None):
        seen = set(bound.get('seen_ids', []))
        feed = (diagnostics or {}).get('adapter') == 'feed'
        revisions, current_revisions = {}, {}
        if archive or feed:
            # The durable queue owns consumed/drafted state. A corrected capture
            # must reach that queue so a source hold can recover, without making
            # an unchanged historical post new again. Keep only one small digest
            # per currently available archive identity, never a revision history.
            from live.account_monitor import source_revision
            current_revisions = {identity(row): source_revision(row) for row in rows}
            if archive:
                revisions = {key: revision for key, revision in
                             (bound.get('archive_revisions') or {}).items()
                             if key in current_revisions}
        bootstrap = max(utc(bound.get('window_start') or moment - timedelta(hours=self.max_age_hours)),
                        moment - timedelta(hours=self.max_age_hours))
        seen_dates = dict(bound.get('seen_dates') or {})
        body_complete = set(bound.get('body_complete_ids') or [])
        retries = {key: value for key, value in (bound.get('body_retries') or {}).items()
                   if utc(value['expires_at']) >= moment}
        recovery_deferred = 0
        if not archive:
            # Historical dedup lives in the monitor database. The polling cursor
            # only needs identities inside its live freshness window, so it does
            # not grow forever with daily feed traffic.
            seen_dates = {key: stamp for key, stamp in seen_dates.items() if utc(stamp) >= bootstrap}
            seen = (seen & set(seen_dates)) if 'seen_dates' in bound else seen
            if feed:
                revisions = {key: revision for key, revision in
                             (bound.get('seen_revisions') or {}).items() if key in seen_dates}
        pending, duplicates, stale, future, undated = [], 0, 0, 0, 0
        observed = set()
        for row in rows:
            key = identity(row)
            if (feed and row.get('content_complete') is not True
                    and key in seen and key not in body_complete):
                # Upgrade checkpoints made before recoverable preview states
                # existed. One public re-check is safe; durable DB identities
                # still prevent any previously generated item being regenerated.
                seen.discard(key)
                seen_dates.pop(key, None)
            unchanged = key in seen and (not (archive or feed) or
                                         revisions.get(key) == current_revisions[key])
            if unchanged or key in observed:
                duplicates += 1
                continue
            observed.add(key)
            try:
                published = utc(row.get('published_at')) if row.get('published_at') else None
            except (ValueError, TypeError, OverflowError):
                published = None
            if published and published > moment:
                # Do not consume a future-dated post; it may become eligible later.
                future += 1
                continue
            if not archive and published and published < bootstrap:
                stale += 1
                continue
            retry = retries.get(key)
            body_hash = hashlib.sha256(str(row.get('original_text', row.get('text', ''))).encode()).hexdigest()
            if (retry and row.get('content_complete') is not True and
                    retry.get('preview_hash') == body_hash and utc(retry['next_retry_at']) > moment):
                recovery_deferred += 1
                continue
            if published is None:
                undated += 1  # Persist for an explicit needs_source hold downstream.
            normalized = {**row, 'published_at': published.isoformat() if published else None}
            pending.append((published or datetime.min.replace(tzinfo=UTC), key, normalized))
        pending.sort(key=lambda value: (value[0], value[1]))
        delivered = pending[:limit]
        revised_items = sum(key in seen for _, key, _ in delivered) if archive or feed else 0
        seen.update(key for _, key, _ in delivered)
        if not archive:
            seen_dates.update({key: (date if date.year > 1 else moment).isoformat()
                               for date, key, _ in delivered})
        valid_dates = [date for date, _, _ in delivered if date.year > 1]
        if bound.get('last_seen'):
            valid_dates.append(utc(bound['last_seen']))
        cursor = {**bound, 'seen_ids': sorted(seen),
                  'window_start': None if archive else bootstrap.isoformat(),
                  'last_seen': max(valid_dates).isoformat() if valid_dates else None}
        if archive:
            # Old identity-only checkpoints make one bounded reconciliation pass.
            # State.enqueue preserves drafted items and only reopens source holds
            # when material content/context has actually improved.
            revisions.update({key: current_revisions[key] for _, key, _ in delivered})
            cursor['archive_revisions'] = revisions
        if not archive:
            cursor['seen_dates'] = seen_dates
            cursor['seen_ids'] = sorted(seen_dates)
            cursor['body_retries'] = retries
            cursor['body_complete_ids'] = sorted(body_complete & set(seen_dates))
            if feed:
                # Digest the publisher input, not its subsequent public-body
                # recovery. An unchanged preview must not repeatedly trigger
                # recovery just because its recovered complete body differs.
                # Legacy identity-only cursors reconcile once, bounded by limit.
                revisions.update({key: current_revisions[key] for _, key, _ in delivered})
                cursor['seen_revisions'] = {key: revision for key, revision in revisions.items()
                                            if key in seen_dates}
        info = {**(diagnostics or {}), 'checked': True, 'source_rows': len(rows),
                'duplicate_skipped': duplicates, 'stale_skipped': stale,
                'future_deferred': future, 'undated': undated, 'backlog': max(0, len(pending) - limit),
                'status': 'archive' if archive else 'fetched',
                'new_items': len(delivered), 'body_recovery_deferred': recovery_deferred,
                'body_recovery_pending': len(retries)}
        if archive:
            info['archive_revision_rechecks'] = revised_items
        elif feed:
            info['feed_revision_rechecks'] = revised_items
        return FetchResult([row for _, _, row in delivered], cursor,
                           len(pending) <= limit and not info.get('retrieval_saturated') and not retries, info)

    def _recover_bodies(self, result, account_id, sid, config, moment):
        from live.source_recovery import SourceRecovery
        from live.account_sources import _media_uncertainty
        host = urlsplit(config['feed_url']).hostname
        hosts = {host}
        if host:
            hosts.add(host[4:] if host.startswith('www.') else 'www.' + host)
        recovery = SourceRecovery(self.capture_root / account_id / sid / 'public_bodies',
                                  allowed_hosts=hosts, fetcher=self.recovery_fetcher)
        attempts, recovered, unresolved = 0, 0, 0
        retries = dict(result.cursor.get('body_retries') or {})
        for index, row in enumerate(result.items):
            key = identity(row)
            if row.get('content_complete') is not True and row.get('url'):
                # Transport is constrained to the subscribed publisher. No
                # credentials, proxy services, or paid-body access are attempted.
                before = row.get('original_text', row.get('text', ''))
                if self.recover_bodies:
                    attempts += 1
                    row = recovery.recover({**row, 'body_recovery': 'public_html'})
                if row.get('content_complete'):
                    recovered += 1
                    row['context_items'] = [*(row.get('context_items') or []), {
                        'kind': 'feed_preview_before_public_body_recovery',
                        'text': before, 'raw_import_ref': row.get('raw_import_ref'),
                        'ownership': 'same publisher feed preview; not a second author'}]
                else:
                    unresolved += 1
                    previous = retries.get(key, {})
                    attempts_so_far = previous.get('attempts', 0) + int(self.recover_bodies)
                    # Retry a currently blocked preview without treating it as a
                    # new publication. A changed feed body bypasses this backoff.
                    retries[key] = {
                        'attempts': attempts_so_far,
                        'preview_hash': hashlib.sha256(str(before).encode()).hexdigest(),
                        'next_retry_at': (moment + timedelta(hours=self.body_retry_hours)).isoformat(),
                        'expires_at': (utc(row['published_at']) + timedelta(hours=self.max_age_hours)).isoformat()
                            if row.get('published_at') else (moment + timedelta(hours=self.max_age_hours)).isoformat(),
                        'status': 'public_body_unresolved'}
                    result.cursor['seen_ids'] = [seen for seen in result.cursor['seen_ids'] if seen != key]
                    result.cursor.get('seen_dates', {}).pop(key, None)
                    result.cursor.get('seen_revisions', {}).pop(key, None)
            if row.get('content_complete'):
                retries.pop(key, None)
                result.cursor['body_complete_ids'] = sorted(set(result.cursor.get('body_complete_ids', [])) | {key})
            result.items[index] = _media_uncertainty(row)
        result.cursor['body_retries'] = retries
        result.complete = (not result.diagnostics.get('backlog') and
                           not result.diagnostics.get('retrieval_saturated') and not retries)
        result.diagnostics.update(body_recovery_attempted=attempts,
                                  body_recovery_succeeded=recovered,
                                  body_recovery_unresolved=unresolved,
                                  body_recovery_pending=len(retries))

    def _x(self, account_id, sid, config, bound, moment, limit):
        if not self.allow_paid_x:
            raise IntakeFailure('paid_x_disabled', retryable=False)
        handle = str(config.get('handle') or sid.removeprefix('x_')).lstrip('@')
        if not re.fullmatch(r'[A-Za-z0-9_]{1,50}', handle):
            raise IntakeFailure('invalid_source_handle', retryable=False)
        # One date partition per source per cycle. A full result page never
        # advances past a possibly unseen gap. Since/until are explicit UTC dates.
        day = utc(bound.get('query_day') or moment - timedelta(hours=self.max_age_hours)).date()
        end_day = day + timedelta(days=1)
        query = f'from:{handle} since:{day.isoformat()} until:{end_day.isoformat()} -filter:retweets'
        cache_ref = bound.get('pending_capture')
        if cache_ref:
            path = Path(cache_ref)
            if not path.resolve().is_relative_to(self.capture_root.resolve()):
                raise IntakeFailure('pending_capture_outside_store', retryable=False)
            try:
                saved = json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                raise IntakeFailure('pending_capture_unreadable', type(exc).__name__) from exc
            if saved.get('account_id') != account_id or saved.get('source_id') != sid or saved.get('query') != query:
                raise IntakeFailure('pending_capture_scope_mismatch', retryable=False)
            return self._x_result(saved['capture'], account_id, sid, handle, bound,
                                  moment, limit, day, path, cached=True)
        from live.xsearch import search
        from ml import budget
        reservation = 'source-monitor-x-' + uuid.uuid4().hex
        try:
            budget.reserve('apify/source-monitor', [], 0, reservation,
                           overhead_usd=self.x_reservation_usd)
        except budget.BudgetExceeded as exc:
            raise IntakeFailure('budget_exceeded', str(exc), retryable=True) from exc
        try:
            capture = (self.x_fetcher or search)(query, max_items=FETCH_CAP,
                raw_directory=self.capture_root / account_id / sid / 'raw')
        except Exception as exc:
            # A failed remote request can still be billed. Keep the reserve until
            # provider evidence is available; never release it as "free".
            budget.settle(reservation, {'prompt_tokens': 0, 'completion_tokens': 0})
            raise IntakeFailure('x_provider_failed', type(exc).__name__) from exc
        budget.settle(reservation, {'prompt_tokens': 0, 'completion_tokens': 0},
                      overhead_actual_usd=capture.get('billed_usd'))
        capture = {**capture, 'budget_reservation': reservation}
        saved = self._snapshot(account_id, sid, {'account_id': account_id,
            'source_id': sid, 'query': query, 'capture': capture})
        return self._x_result(capture, account_id, sid, handle, bound, moment,
                              limit, day, saved)

    def _x_result(self, capture, account_id, sid, handle, bound, moment, limit, day, saved, cached=False):
        rows, rejected = [], 0
        for row in capture.get('rows', []):
            author = str(row.get('author_handle') or row.get('handle') or '').lstrip('@').lower()
            if author != handle.lower():
                rejected += 1
                continue
            rows.append({**row, 'source_id': sid})
        returned = capture.get('retrieval_diagnostics', {}).get('dataset_items', len(capture.get('rows', [])))
        saturated = returned >= FETCH_CAP
        result = self._page(rows, bound, moment, limit, diagnostics={
            'adapter': 'apify_x', 'query': capture.get('query'),
            'billed_usd': 0 if cached else capture.get('billed_usd'), 'cached_backlog': cached,
            'budget_reservation': capture.get('budget_reservation'), 'rejected_author': rejected,
            'capture_ref': capture.get('raw_snapshot'), 'apify_run_id': capture.get('apify_run_id'),
            'retrieval_saturated': saturated,
            'coverage': 'bounded search sample; upstream is not a complete thread/timeline guarantee'})
        advance = not saturated and not result.diagnostics['backlog'] and day < moment.date()
        result.cursor['query_day'] = (day + timedelta(days=1) if advance else day).isoformat()
        # A saturated date partition needs an explicit operator recovery (narrower
        # partition or a provider with pagination), not endless paid retries of
        # the same 200 records followed by silently skipping the unseen remainder.
        result.cursor['pending_capture'] = str(saved) if result.diagnostics['backlog'] or saturated else None
        result.complete = result.complete and (day == moment.date())
        result.diagnostics['window_complete'] = not saturated and not result.diagnostics['backlog']
        result.diagnostics['status'] = 'coverage_gap_saturated' if saturated else 'fetched'
        return result
