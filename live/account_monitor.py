"""Durable account-first monitor. Generates review candidates, never publishes.

SQLite checkpoints are committed after input rows are persisted, before model calls.
The existing immutable Store is the dashboard's store; no export/import is needed.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import timedelta
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

from live.account_intelligence import Store, DEFAULT, ROOT, now, time, digest
from live.account_sources import SourcePipeline, ingest, valid_candidate, universes, source_key, _media_uncertainty
from live.source_identity import aliases
from live.account_source_adaptation import execution_failed, execution_failure, fidelity_hold

CONFIG = ROOT / 'live/account_monitor.json'
ACCOUNTS = ('en_morris_archive', 'zh_macro', 'zh_industry')


def source_revision(row):
    """Only changed source/context can reopen a source hold; polling isn't evidence."""
    fields = ('original_text', 'text', 'published_at', 'content_complete', 'title',
              'media_dependencies', 'context_items', 'quoted_post', 'reply_to',
              'thread_id', 'entity_glossary', 'extraction_status', 'truncated', 'recovery',
              'source_language', 'author_id', 'author_name', 'author_handle', 'post_type',
              'thread_post_ids', 'required_context_urls', 'external_links', 'platform', 'source_type')
    observational = {'at', 'fetched_at', 'snapshot_at', 'checked_at', 'recorded_at',
                     'retrieved_at', 'captured_at', 'updated_at', 'attempted_at',
                     'document_ref', 'raw_import_ref', 'capture_ref'}
    def material(value):
        if isinstance(value, dict):
            return {k: material(v) for k, v in value.items() if k not in observational}
        if isinstance(value, list):
            return [material(v) for v in value]
        return value
    return digest([material({key: row.get(key) for key in fields}),
                   bool(row.get('fetched_at') or row.get('snapshot_at'))])


def configuration():
    cfg = json.loads(CONFIG.read_text())
    if tuple(cfg['accounts']) != ACCOUNTS or cfg.get('publishing_enabled') is not False:
        raise ValueError('Monitor is restricted to the three owned accounts and human review')
    return cfg


class State:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'monitor.sqlite3'
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sources (
                    account TEXT NOT NULL, source TEXT NOT NULL, cursor TEXT NOT NULL DEFAULT '{}',
                    last_checked TEXT, last_seen TEXT, status TEXT, error TEXT,
                    PRIMARY KEY(account,source));
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY, account TEXT NOT NULL, source TEXT NOT NULL,
                    row_json TEXT NOT NULL, status TEXT NOT NULL, candidate_id TEXT,
                    last_run TEXT, attempts INTEGER NOT NULL DEFAULT 0, next_retry TEXT,
                    failure TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS identities (
                    account TEXT NOT NULL, alias TEXT NOT NULL, item_id TEXT NOT NULL,
                    PRIMARY KEY(account,alias));
                CREATE TABLE IF NOT EXISTS cycles (
                    id TEXT PRIMARY KEY, started_at TEXT NOT NULL, as_of TEXT NOT NULL,
                    finished_at TEXT, status TEXT NOT NULL, report TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS queue ON items(account,status,next_retry);
            ''')
            # Waiting for funding must not exhaust the later transport/JSON retry
            # allowance. Keep the original total attempt counter for history.
            columns = {r['name'] for r in db.execute('PRAGMA table_info(items)')}
            if 'retry_failures' not in columns:
                db.execute('ALTER TABLE items ADD COLUMN retry_failures INTEGER NOT NULL DEFAULT 0')
                db.execute("UPDATE items SET retry_failures=attempts WHERE status IN ('retry','blocked_execution') "
                           "AND failure NOT IN ('budget_exhausted','provider_quota','budget_exceeded')")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def meta(self, key, value=None):
        with self.db() as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value)))
                return value
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def rows(self, table):
        if table not in {'items', 'sources', 'cycles'}:
            raise ValueError('Unknown monitor table')
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM ' + table)]

    def _revision_allowed(self, old, sid, row):
        previous = json.loads(old['row_json'])
        if (old['status'] not in {'blocked_source', 'blocked_execution', 'retry'}
                or row.get('content_complete') is not True
                or old['source'] != sid or previous.get('url') != row.get('url')
                or (previous.get('author_name') or previous.get('author')) != (row.get('author_name') or row.get('author'))
                or any(previous.get(key) and row.get(key) and previous[key] != row[key]
                       for key in ('source_id', 'author_id', 'author_handle'))
                or source_revision(previous) == source_revision(row)):
            return False
        if old['status'] == 'blocked_source' and not old['candidate_id']:
            return True
        # A QA execution failure can retain a real draft. Improved source input
        # must never silently rewrite that draft, or override a saved NONE/SKIP.
        if not old['last_run'] or not old['candidate_id']:
            return False
        store = Store(self.root)
        try:
            parent = store.get('runs', old['last_run'])
            if (parent.get('account_id') != old['account'] or
                    parent.get('inbox_candidate_id') != old['candidate_id'] or
                    old['status'] != 'blocked_source' and not execution_failed(parent)):
                return False
            related = [r for r in store.rows('runs') if r.get('account_id') == old['account']
                       and r.get('inbox_candidate_id') == old['candidate_id']]
            return bool(related) and not any(r.get('candidates') or r.get('status') == 'ignore' or
                (r.get('source_adaptation') or {}).get('final_draft') or
                ((r.get('source_adaptation') or {}).get('localization') or {}).get('text') or
                ((r.get('source_adaptation') or {}).get('route') or {}).get('decision') in {'NONE', 'SKIP'}
                for r in related)
        except (ValueError, OSError, TypeError):
            return False  # Missing historical evidence is not permission to rewrite.

    def enqueue(self, account, sid, row, at, *, status='pending', candidate_id=None, last_run=None):
        keys = aliases(row)
        if not keys:
            raise ValueError('Source has no stable identity or text')
        item_id = 'monitor-' + digest([account, keys])[:24]
        with self.db() as db:
            ids = {r[0] for key in keys for r in db.execute(
                'SELECT item_id FROM identities WHERE account=? AND alias=?', (account, key))}
            if ids:
                # One bridge can join a thread/post/content identity. All aliases
                # stay consumed; an already drafted item is never regenerated.
                members = [db.execute('SELECT * FROM items WHERE id=?', (key,)).fetchone() for key in ids]
                priority = {'drafted': 0, 'historical_processed': 0, 'skipped': 1, 'executing': 2}
                old = min(members, key=lambda r: (priority.get(r['status'], 3), r['created_at'], r['id']))
                # A newly discovered thread/event bridge can join two formerly
                # independent pending rows. Retain both records but consume the
                # extra queue entries and redirect their aliases atomically.
                for member in members:
                    if member['id'] != old['id']:
                        db.execute('UPDATE identities SET item_id=? WHERE account=? AND item_id=?',
                                   (old['id'], account, member['id']))
                        db.execute("UPDATE items SET status='duplicate',failure=?,updated_at=? WHERE id=?",
                                   ('duplicate_of:' + old['id'], at, member['id']))
                recover = self._revision_allowed(old, sid, row)
                if recover:
                    db.execute("UPDATE items SET row_json=?,status='pending',candidate_id=NULL,"
                               "next_retry=NULL,failure=NULL,retry_failures=0,updated_at=? WHERE id=?",
                               (json.dumps(row, ensure_ascii=False), at, old['id']))
                for key in keys:
                    db.execute('INSERT OR IGNORE INTO identities VALUES (?,?,?)', (account, key, old['id']))
                return old['id'], not recover
            db.execute('INSERT INTO items(id,account,source,row_json,status,candidate_id,last_run,created_at,updated_at) '
                       'VALUES(?,?,?,?,?,?,?,?,?)',
                       (item_id, account, sid, json.dumps(row, ensure_ascii=False), status,
                        candidate_id, last_run, at, at))
            db.executemany('INSERT INTO identities VALUES (?,?,?)', [(account, k, item_id) for k in keys])
        return item_id, False

    def update(self, item_id, **values):
        allowed = {'status','candidate_id','last_run','attempts','retry_failures','next_retry','failure','updated_at'}
        if not values or not set(values) <= allowed:
            raise ValueError('Invalid monitor item update')
        with self.db() as db:
            db.execute('UPDATE items SET ' + ','.join(k + '=?' for k in values) + ' WHERE id=?',
                       (*values.values(), item_id))


def failure_code(run):
    result = run.get('source_adaptation') or {}
    failure = execution_failure(result)
    if failure.get('code'):
        return failure['code']
    why = str(result.get('why') or run.get('error_type') or '')
    for pattern, code in [('BudgetExceeded','budget_exhausted'), ('ProviderQuota','provider_quota'),
                          ('JSON','invalid_json'), ('Timeout','provider_timeout')]:
        if pattern in why:
            return code
    return 'generation_failed'


def qa_only_followup(run, runs_by_id):
    """Recognize old QA resumptions from immutable ancestry, without backfilling it.

    Older batch follow-ups predate execution_checkpoint metadata. They are not
    new daily posts when their captured source and entire body remain exact.
    Legacy duplicate inbox IDs require matching source text hash, URL and author.
    A changed/missing ancestor or changed prose stops the inference.
    """
    from live.account_source_adaptation import qa_checkpoint
    bodies = [c.get('text') for c in run.get('candidates', [])]
    if not bodies or not all(isinstance(body, str) and body for body in bodies):
        return False
    def same_source(left, right):
        a = (left.get('source_adaptation') or {}).get('source') or {}
        b = (right.get('source_adaptation') or {}).get('source') or {}
        keys = ('source_hash', 'url', 'author_name')
        return (all(a.get(k) and a.get(k) == b.get(k) for k in keys)
                and a.get('original_text') and b.get('original_text')
                and digest(a['original_text']) == a['source_hash']
                and digest(b['original_text']) == b['source_hash'])
    current, seen = run, {run['id']}
    while current.get('follow_up_of'):
        parent = runs_by_id.get(current['follow_up_of'])
        if (not parent or parent['id'] in seen or parent.get('account_id') != run.get('account_id')
                or not run.get('inbox_candidate_id')
                or (parent.get('inbox_candidate_id') != run['inbox_candidate_id'] and not same_source(parent, run))
                or [c.get('text') for c in parent.get('candidates', [])] != bodies):
            return False
        if qa_checkpoint(parent) or current.get('execution_checkpoint') or (
                current.get('source_adaptation') or {}).get('execution_checkpoint'):
            return True
        seen.add(parent['id'])
        current = parent
    return False


def daily_draft_count(runs, account_id, cutoff):
    by_id = {run['id']: run for run in runs}
    return len({run.get('inbox_candidate_id', run['id']) for run in runs
                if run.get('account_id') == account_id and run.get('candidates')
                and run.get('monitor_as_of', run.get('recorded_at', ''))[:10] == cutoff[:10]
                and not qa_only_followup(run, by_id)})


class Monitor:
    def __init__(self, store=None, *, poller=None, pipeline=None, config=None):
        self.store = store or Store()
        self.state = State(self.store.root)
        self.config = config or configuration()
        if list(self.config['accounts']) != list(ACCOUNTS):
            raise ValueError('Three fixed accounts required')
        if poller is None:
            from live.monitor_intake import Poller
            poller = Poller(self.store.root.parent / 'monitor_captures',
                            allow_paid_x=self.config['allow_paid_x'])
        self.poller = poller
        self.pipeline = pipeline or SourcePipeline(self.store)

    def heartbeat(self, daemon=False):
        self.state.meta('heartbeat', {'at': now(), 'pid': os.getpid(), 'daemon': daemon})

    def seed_consumed(self):
        """Existing drafts/decisions remain consumed across the first deployment."""
        if self.state.meta('seeded'):
            return
        runs = self.store.rows('runs')
        latest = {}
        for run in runs:
            if run.get('pipeline') == 'account_source':
                latest[run.get('inbox_candidate_id')] = run
        for candidate in self.store.rows('inbox'):
            aid = candidate['account_id']
            if aid not in ACCOUNTS:
                continue
            run = latest.get(candidate['id'])
            source = self.store.get('sources', candidate['source_id'])
            if run is None:
                status = 'pending'
            elif execution_failed(run):
                from live.account_source_adaptation import qa_checkpoint
                terminal = failure_code(run) in {'content_filter', 'invalid_account', 'checkpoint_mismatch'} or (
                    failure_code(run) == 'source_contract' and not qa_checkpoint(run))
                status = 'blocked_execution' if terminal else 'retry'
            elif run.get('candidates') or run.get('status') == 'ignore':
                status = 'historical_processed'
            else:
                status = 'blocked_source'
            key, _ = self.state.enqueue(aid, candidate['canonical_source_id'], source, now(),
                status=status, candidate_id=candidate['id'], last_run=run['id'] if run else None)
            if run and status in {'retry', 'blocked_execution', 'blocked_source'}:
                code = failure_code(run) if status != 'blocked_source' else run.get('status')
                self.state.update(key, attempts=1, failure=code,
                    retry_failures=int(status != 'blocked_source' and code not in {
                        'budget_exhausted','provider_quota','budget_exceeded'}))
        self.state.meta('seeded', {'at': now(), 'basis': 'existing immutable account-source runs'})

    @staticmethod
    def counters(account_id):
        return {'account_id': account_id, 'sources_checked': 0, 'new_sources': 0,
                'selected': 0, 'generated': 0, 'blocked': 0, 'no_post': False,
                'no_post_reason': None, 'duplicate_skipped': 0, 'stale_skipped': 0,
                'selection_skipped': 0, 'deferred': 0, 'failures': [],
                'open_blocks': 0,
                'reconciled_runs': [], 'provider_recoveries': [], 'execution_recoveries': [], 'context_captured': 0,
                'dashboard_ids': [], 'reused_dashboard_ids': [], 'source_checks': []}

    def run_cycle(self, *, as_of=None, mode='live'):
        cutoff = time(as_of or now()).isoformat()
        if mode not in {'live', 'replay'}:
            raise ValueError('Invalid cycle mode')
        with (self.store.root / 'monitor.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {'status': 'already_running', 'publishing_enabled': False}
            try:
                return self._cycle(cutoff, mode)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _cycle(self, cutoff, mode):
        self.seed_consumed()
        with self.state.db() as db:
            db.execute("UPDATE cycles SET status='interrupted',finished_at=? WHERE status='running'", (now(),))
            db.execute("UPDATE items SET status='pending',failure='interrupted_process' WHERE status='executing'")
        cid = 'cycle-' + uuid.uuid4().hex
        report = {'id': cid, 'started_at': now(), 'as_of': cutoff, 'mode': mode,
                  'status': 'running', 'accounts': [], 'publishing_enabled': False}
        with self.state.db() as db:
            db.execute('INSERT INTO cycles VALUES (?,?,?,?,?,?)',
                       (cid, report['started_at'], cutoff, None, 'running', json.dumps(report)))
        cfgs = {u['account_id']: u for u in universes()}
        for aid in ACCOUNTS:
            summary = self.counters(aid)
            report['accounts'].append(summary)
            try:
                self._reconcile(aid, cutoff, summary)
                self._poll(aid, cfgs[aid], cutoff, summary)
                self._generate(aid, cfgs[aid], cutoff, summary, cid, mode)
                items = [r for r in self.state.rows('items') if r['account'] == aid]
                queued = [r for r in items if r['status'] in {'pending','retry','executing'}]
                summary['deferred'] = len(queued)
                summary['open_blocks'] = sum(r['status'] in {'blocked_source','blocked_execution'} for r in items)
                # No-post means a successful editorial/empty outcome, not an outage.
                if not summary['generated'] and not summary['blocked'] and not summary['open_blocks'] and not summary['failures'] and not queued:
                    summary['no_post'] = True
                    summary['no_post_reason'] = ('no_worthwhile_content' if summary['selection_skipped']
                                                 else 'no_new_eligible_content')
                summary['last_cycle_at'] = cutoff
            except Exception as exc:
                summary['failures'].append({'stage': 'account', 'code': type(exc).__name__})
            self._save_report(report)
        report.update(status='completed_with_blocks' if any(a['failures'] or a['blocked'] or a['open_blocks'] for a in report['accounts'])
                      else 'completed', finished_at=now())
        self._save_report(report)
        output = self.store.root.parent / 'monitor_cycles'
        output.mkdir(parents=True, exist_ok=True)
        (output / (cid + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        return report

    def _save_report(self, report):
        with self.state.db() as db:
            db.execute('UPDATE cycles SET status=?,finished_at=?,report=? WHERE id=?',
                       (report['status'], report.get('finished_at'), json.dumps(report, ensure_ascii=False), report['id']))

    def _poll(self, aid, universe, cutoff, summary):
        for sub in universe['subscriptions']:
            if not sub.get('enabled') or sub['role'] not in {'CORE','SECONDARY','EVENT_ONLY'}:
                continue
            sid = sub['source_id']
            summary['sources_checked'] += 1
            with self.state.db() as db:
                prior = db.execute('SELECT * FROM sources WHERE account=? AND source=?', (aid,sid)).fetchone()
            cursor = None
            try:
                cursor = json.loads(prior['cursor']) if prior else None
                result = self.poller.fetch(aid, sub, cursor, as_of=cutoff, limit=self.config['fetch_limit'])
                from live.source_context import ContextStore, is_context_source
                context_items = getattr(result, 'context_items', [])
                if is_context_source(sid) and result.items:
                    raise ValueError('Official fact sources cannot enqueue content candidates')
                context_counts = ContextStore(self.store.root).record(aid, sid, context_items, cutoff) if context_items else {}
                summary['context_captured'] += context_counts.get('new', 0)
                new, duplicates = 0, 0
                for row in result.items:
                    # Do not trust a scraper's source_id to cross account boundaries.
                    try:
                        if source_key(row) != sid:
                            raise ValueError('Fetched source identity does not match subscribed source')
                    except (ValueError,TypeError,AttributeError):
                        key = 'quarantine-' + digest([aid,sid,row])[:24]
                        self.state.meta(key, {'account_id':aid,'source_id':sid,'row':row,
                                             'reason':'source_identity_rejected','recorded_at':cutoff})
                        summary['failures'].append({'source_id':sid,'stage':'intake',
                            'code':'source_identity_rejected','quarantine_id':key,
                            'url':row.get('url') if isinstance(row,dict) else None})
                        continue
                    _, duplicate = self.state.enqueue(aid, sid, row, cutoff)
                    duplicates += int(duplicate)
                    new += int(not duplicate)
                    summary['new_sources'] += int(not duplicate)
                    summary['duplicate_skipped'] += int(duplicate)
                diagnostics = result.diagnostics or {}
                duplicates += int(diagnostics.get('duplicate_skipped', 0))
                summary['duplicate_skipped'] += int(diagnostics.get('duplicate_skipped', 0))
                summary['stale_skipped'] += int(diagnostics.get('stale_skipped', 0))
                catching_up = (not diagnostics.get('retrieval_saturated') and
                               (diagnostics.get('backlog', 0) > 0 or diagnostics.get('window_complete') is True))
                body_pending = diagnostics.get('body_recovery_pending',0) > 0 and not diagnostics.get('retrieval_saturated')
                status = ('checked' if result.complete else 'body_recovery_pending' if body_pending else
                          'catchup_pending' if catching_up else 'partial_coverage')
                dates = []
                for row in [*result.items, *context_items]:
                    try:
                        if row.get('published_at'):
                            dates.append(time(ingest_date(row['published_at'])).isoformat())
                    except (ValueError,TypeError,AttributeError):
                        pass  # Undated rows remain durable blocked-source items.
                if prior and prior['last_seen']:
                    dates.append(prior['last_seen'])
                last_seen = max(dates, key=lambda d: time(ingest_date(d))) if dates else (prior['last_seen'] if prior else None)
                # All enqueue transactions completed before this checkpoint.
                with self.state.db() as db:
                    db.execute('INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?)',
                        (aid,sid,json.dumps(result.cursor),cutoff,last_seen,status,None))
                summary['source_checks'].append({'source_id':sid,'status':status,'new_sources':new,
                    'duplicate_skipped':duplicates,'diagnostics':diagnostics, 'context':context_counts})
                if status == 'partial_coverage':
                    summary['failures'].append({'source_id':sid,'stage':'fetch','code':'partial_coverage'})
            except Exception as exc:
                code = getattr(exc, 'code', type(exc).__name__)
                with self.state.db() as db:
                    db.execute('INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?)',
                        (aid,sid,prior['cursor'] if prior else json.dumps(cursor or {}),cutoff,prior['last_seen'] if prior else None,'failed',str(code)))
                summary['failures'].append({'source_id':sid,'stage':'fetch','code':code})
                summary['source_checks'].append({'source_id':sid,'status':'failed','code':code})

    def _reconcile(self, aid, cutoff, summary):
        """Adopt immutable saved follow-ups before retrying or checking today's quota."""
        runs = [r for r in self.store.rows('runs') if r.get('pipeline') == 'account_source'
                and r.get('account_id') == aid]
        for item in self.state.rows('items'):
            if item['account'] != aid or not item['candidate_id'] or item['status'] in {'duplicate', 'skipped', 'stale'}:
                continue
            related = [r for r in runs if r.get('inbox_candidate_id') == item['candidate_id']]
            if not related:
                continue
            latest = related[-1]
            # Terminal reviewed/held content is never reopened by a provider change.
            if latest['id'] != item['last_run'] or (item['status'] in {'pending', 'blocked_execution', 'retry'}
                    and not execution_failed(latest)):
                self._record_run(item, latest, {r['id'] for r in related}, cutoff, summary)
                summary['reconciled_runs'].append(latest['id'])
                item = next(r for r in self.state.rows('items') if r['id'] == item['id'])
            elif item['status'] in {'drafted', 'historical_processed'} and execution_failed(latest):
                # Older code consumed a candidate even when its QA API call failed.
                self._record_run(item, latest, {latest['id']}, cutoff, summary)
                item = next(r for r in self.state.rows('items') if r['id'] == item['id'])
            if item['status'] != 'blocked_execution' or not execution_failed(latest):
                continue
            from live.content_stages import follow_up_repairs
            adaptation = latest.get('source_adaptation') or {}
            active_config = latest.get('stage_configuration') or adaptation.get('stage_configuration') or {}
            applied = {r['name'] for r in active_config.get('execution_repairs', [])}
            unused = [r for r in follow_up_repairs({**latest, 'source_adaptation': {
                **adaptation, 'execution_failure': execution_failure(adaptation)}}) if r['name'] not in applied]
            if unused:
                key = 'execution-recovery-' + digest([item['id'], latest['id'], [r['name'] for r in unused]])[:24]
                if not self.state.meta(key):
                    receipt = {'item_id':item['id'], 'parent_run_id':latest['id'], 'repairs':unused,
                        'reason':'new_supported_execution_repair', 'retry_failures_preserved':item['retry_failures'], 'at':cutoff}
                    with self.state.db() as db:
                        db.execute('INSERT INTO meta VALUES (?,?)', (key,json.dumps(receipt)))
                        db.execute("UPDATE items SET status='retry',next_retry=?,failure=?,updated_at=? WHERE id=?",
                            (cutoff, 'execution_repair_available:' + failure_code(latest), cutoff, item['id']))
                    summary['execution_recoveries'].append(receipt)
                    continue
            if failure_code(latest) not in {'content_filter','provider_error','provider_timeout',
                    'provider_quota','budget_exhausted','budget_exceeded','invalid_json','response_incomplete','model_response_contract'}:
                continue
            configured = getattr(self.pipeline, 'generation_configuration', None) or {}
            active = configured.get('provider')
            original = latest.get('stage_configuration') or (latest.get('source_adaptation') or {}).get('stage_configuration') or {}
            if not active or not original.get('provider') or original['provider'] == active:
                continue
            # Explicit configuration change authorizes one new provider attempt;
            # durable receipts prevent a crash or repeated polls rearming it.
            key = 'provider-recovery-' + digest([item['id'], latest['id'], active])[:24]
            if self.state.meta(key):
                continue
            receipt = {'item_id': item['id'], 'parent_run_id': latest['id'], 'from_provider': original['provider'],
                       'to_provider': active, 'reason': 'explicit_configured_provider_change', 'at': cutoff}
            with self.state.db() as db:
                db.execute('INSERT INTO meta VALUES (?,?)', (key, json.dumps(receipt)))
                db.execute("UPDATE items SET status='retry',next_retry=?,retry_failures=0,failure=?,updated_at=? WHERE id=?",
                           (cutoff, 'provider_changed:' + failure_code(latest), cutoff, item['id']))
            summary['provider_recoveries'].append(receipt)

    def _generate(self, aid, universe, cutoff, summary, cycle_id, mode):
        rows = [r for r in self.state.rows('items') if r['account'] == aid and r['status'] in {'pending','retry'}
                and (not r['next_retry'] or time(r['next_retry']) <= time(cutoff))]
        rows.sort(key=lambda r: (r['attempts'],r['created_at'],r['id']))
        # A failed source cannot consume all execution slots every cycle.
        buckets = {}
        for row in rows:
            buckets.setdefault(row['source'], []).append(row)
        fair = []
        while any(buckets.values()):
            for bucket in buckets.values():
                if bucket:
                    fair.append(bucket.pop(0))
        day_count = daily_draft_count(self.store.rows('runs'), aid, cutoff)
        attempted = 0
        for item in fair:
            stored = [r for r in self.store.rows('runs') if item['candidate_id']
                      and r.get('inbox_candidate_id') == item['candidate_id'] and r.get('account_id') == aid]
            if item['status'] == 'pending' and stored:
                # Reconcile a committed draft even if it already filled today's
                # quota, or its source has aged while the process was stopped.
                self._record_run(item, stored[-1], {r['id'] for r in stored}, cutoff, summary)
                continue
            qa_resume = item['status'] == 'retry' and any(r['id'] == item['last_run'] and
                execution_failure(r.get('source_adaptation') or {}).get('stage') == 'qa' and r.get('candidates') for r in stored)
            if attempted >= self.config['max_attempts_per_account_cycle'] or (not qa_resume and day_count >= self.config['max_drafts_per_account_day']):
                continue
            row = json.loads(item['row_json'])
            reason = None
            try:
                published = time(ingest_date(row.get('published_at')))
                if published > time(cutoff):
                    reason = 'future_publication'
                elif not qa_resume and universe['mode'] != 'evergreen' and (time(cutoff)-published).total_seconds() > self.config['max_source_age_hours']*3600:
                    reason = 'stale_source'
            except (ValueError,TypeError):
                reason = 'publication_date_missing'
            if reason:
                self.state.update(item['id'], status='stale' if reason == 'stale_source' else 'blocked_source',
                                  failure=reason, updated_at=cutoff)
                summary['stale_skipped' if reason == 'stale_source' else 'blocked'] += 1
                continue
            if aid == 'en_morris_archive' and re.search(r'不(?:只)?是[^。！？]{0,180}而是',row.get('original_text',row.get('text',''))):
                self.state.update(item['id'],status='skipped',failure='morris_source_style_preference',updated_at=cutoff)
                summary['selection_skipped'] += 1
                continue
            try:
                if item['status'] == 'retry' and item['candidate_id']:
                    # Execution retries keep the immutable admitted snapshot.
                    # Annotation-version updates alone cannot create another inbox
                    # identity; real source revisions use the pending path above.
                    existing, _ = valid_candidate(self.store, aid, item['candidate_id'])
                    result = {'admitted': True, 'candidate': existing, 'duplicate': True}
                else:
                    result = ingest(self.store,aid,_media_uncertainty(row),batch_id='daily-monitor', fixture_id=cycle_id if mode=='replay' else None)
                if not result['admitted']:
                    self.state.update(item['id'],status='skipped',failure='not_admitted',updated_at=cutoff)
                    summary['selection_skipped'] += 1
                    continue
                candidate = result['candidate']
                self.state.update(item['id'],candidate_id=candidate['id'],status='executing',updated_at=cutoff)
                known = {r['id'] for r in self.store.rows('runs') if r.get('account_id')==aid}
                # Recovery after a crash between Store.append and item commit uses
                # the stored run, not another paid call. A known failed run gets an
                # explicit follow-up identity on its scheduled retry.
                parent = item['last_run'] if item['status']=='retry' else None
                revision_parent = None
                if item['status'] == 'pending' and item['last_run']:
                    ancestor = self.store.get('runs', item['last_run'])
                    if ancestor.get('inbox_candidate_id') != candidate['id']:
                        revision_parent = ancestor['id']
                run = self.pipeline.run(aid,candidate['id'],parent,
                    monitor_context={'cycle_id':cycle_id,'as_of':cutoff,'mode':mode,
                                     'source_revision_of': revision_parent})
                attempted += 1
                day_count += self._record_run(item, run, known, cutoff, summary)
            except Exception as exc:
                attempted += 1
                code=type(exc).__name__
                retry_failures=item.get('retry_failures',0)+1
                self.state.update(item['id'],status='retry' if retry_failures < self.config['max_retry_attempts'] else 'blocked_execution',
                    attempts=item['attempts']+1,retry_failures=retry_failures,failure=code,updated_at=cutoff,
                    next_retry=(time(cutoff)+timedelta(seconds=self.config['retry_seconds'])).isoformat())
                summary['blocked'] += 1
                summary['failures'].append({'source_id':item['source'],'stage':'generation','code':code,'item_id':item['id']})

    def _record_run(self, item, run, known, cutoff, summary):
        adaptation = run.get('source_adaptation') or {}
        route = adaptation.get('route') or {}
        reused = run['id'] in known
        summary['selected'] += int(not reused and route.get('decision') == 'MOVE')
        updates = dict(last_run=run['id'], attempts=item['attempts']+1, updated_at=cutoff,
                       next_retry=None, failure=None, retry_failures=0)
        generated = 0
        if run.get('candidates'):
            updates['status'] = 'drafted'
            checkpoint = run.get('execution_checkpoint') or adaptation.get('execution_checkpoint')
            if reused or checkpoint:
                summary['duplicate_skipped'] += 1
            else:
                generated = len(run['candidates'])
                summary['generated'] += generated
            summary['reused_dashboard_ids' if reused or checkpoint else 'dashboard_ids'].extend(c['id'] for c in run['candidates'])
            if not execution_failed(run) and (run['status'] == 'machine_hold' or fidelity_hold(adaptation)):
                summary['blocked'] += 1
        if run['status'] == 'ignore' and not run.get('candidates'):
            updates['status'] = 'skipped'
            summary['selection_skipped'] += 1
        elif execution_failed(run):
            code = failure_code(run)
            from live.account_source_adaptation import qa_checkpoint
            retryable = code not in {'content_filter','source_contract','invalid_account','checkpoint_mismatch'} or (
                code == 'source_contract' and qa_checkpoint(run))
            external = code in {'budget_exhausted','provider_quota','budget_exceeded'}
            updates['retry_failures'] = item.get('retry_failures',0) + int(not external)
            # A later stage may reveal its first capacity/format failure after
            # earlier stages recovered. Permit an unused, explicitly recorded
            # repair once; an already-applied repair cannot extend retries.
            from live.content_stages import follow_up_repairs
            active = run.get('stage_configuration') or adaptation.get('stage_configuration') or {}
            applied = {r['name'] for r in active.get('execution_repairs', [])}
            new_repair = any(r['name'] not in applied for r in follow_up_repairs(run))
            retry = retryable and (external or new_repair or
                                   updates['retry_failures'] < self.config['max_retry_attempts'])
            delay = (max(3600, self.config['retry_seconds']) if external else
                     0 if new_repair else self.config['retry_seconds'])
            updates.update(status='retry' if retry else 'blocked_execution', failure=code,
                           next_retry=(time(cutoff)+timedelta(seconds=delay)).isoformat() if retry else None)
            summary['blocked'] += 1
            summary['failures'].append({'source_id':item['source'],
                'stage':execution_failure(adaptation).get('stage','generation'),
                'code':code,'run_id':run['id'],'item_id':item['id']})
        elif not run.get('candidates') and run['status'] != 'ignore':
            updates.update(status='blocked_source', failure=adaptation.get('draft_status') or run['status'])
            summary['blocked'] += 1
        self.state.update(item['id'], **updates)
        return int(bool(generated))


def ingest_date(value):
    from live.account_sources import _date
    return _date(value)


def monitor_status(store_root=None):
    from ml import budget
    ledger = budget._load()
    cap = float(ledger.get('cap_usd', budget.DEFAULT_CAP_USD))
    spent = float(ledger.get('spent_usd', 0))
    root = Path(store_root or DEFAULT)
    base = {'enabled':configuration()['enabled'],'configured':True,'daemon_running':False,
            'running':False,'heartbeat_at':None,'last_cycle':None,'accounts':[], 'publishing_enabled':False,
            'budget': {'cap_usd': cap, 'spent_usd': spent, 'remaining_usd': round(cap-spent, 6),
                       'basis': 'local reservation ledger, not provider balance'}}
    if not (root/'monitor.sqlite3').exists():
        return base
    # Dashboard polling is observational: never create schemas, switch journal
    # modes, or take a writer transaction merely to display a status.
    with sqlite3.connect((root/'monitor.sqlite3').resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        heartbeat_row = db.execute("SELECT value FROM meta WHERE key='heartbeat'").fetchone()
        heartbeat = json.loads(heartbeat_row[0]) if heartbeat_row else {}
        cycles = [dict(r) for r in db.execute('SELECT * FROM cycles ORDER BY started_at')]
        sources = [dict(r) for r in db.execute('SELECT * FROM sources')]
        items = [dict(r) for r in db.execute('SELECT account,status FROM items')]
    alive=False
    if heartbeat.get('pid'):
        try:
            os.kill(heartbeat['pid'],0)
            alive=(time(now())-time(heartbeat['at'])).total_seconds()<120
        except PermissionError:
            # EPERM means the process exists but this reader cannot signal it.
            # A fresh heartbeat remains authoritative for sandboxed readers.
            alive=(time(now())-time(heartbeat['at'])).total_seconds()<120
        except (OSError,ValueError):
            pass
    last=json.loads(cycles[-1]['report']) if cycles else None
    if last and cycles[-1]['status'] != last.get('status'):
        last.update(status=cycles[-1]['status'], finished_at=cycles[-1]['finished_at'])
    return {**base,'heartbeat_at':heartbeat.get('at'),'daemon_running':alive and heartbeat.get('daemon') is True,
            'running':alive and bool(last and last['status']=='running'),'last_cycle':last,
            'accounts':last['accounts'] if last else [],'sources':sources,
            'queue_counts':{aid:{status:sum(r['account']==aid and r['status']==status for r in items)
                           for status in ('pending','retry','drafted','blocked_source','blocked_execution','skipped','stale')}
                           for aid in ACCOUNTS}}
