"""Small, append-only contracts for the opt-in owned-account editorial desk.

No publishing, scheduler, training or implicit belief adoption. Recorded time and
effective time are distinct; historical replay never sees a later human decision.
"""
from __future__ import annotations
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
import fcntl
import json
import math
import re
import uuid

from live.distillation_source import digest, now
from live.source_hygiene import annotate, postcheck

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'runs/account_sources_v1/store'
LEGACY = ROOT / 'runs/account_intelligence_v1/store'
KINDS = {'sources', 'research', 'research_reviews', 'events', 'runs', 'state_proposals', 'state_actions',
         'reviews', 'decision_feedback', 'publications', 'engagement', 'inbox'}
STATE_KINDS = {'framework', 'view', 'topic_preference', 'evidence_preference', 'ignore_preference', 'style_preference'}


def require(test, message):
    if not test:
        raise ValueError(message)


def time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(result.tzinfo is not None, 'Timezone required')
        return result.astimezone(timezone.utc)
    except (AttributeError, TypeError):
        raise ValueError('ISO timestamp required') from None


def accounts(active_only=False):
    config = json.loads((ROOT / 'live/owned_accounts.json').read_text())
    return [{**a, 'principles': config['shared'], 'basis': config['basis'],
             'charter_version': config['version']} for a in config['accounts']
            if not active_only or a.get('enabled') is True]


def account(key):
    rows = [a for a in accounts() if a['id'] == key]
    require(len(rows) == 1, 'Unknown owned account')
    return rows[0]


class Store:
    def __init__(self, root=DEFAULT):
        self.root = Path(root)
        # Frozen evaluations remain readable; all new writes go to the new store.
        self.legacy = LEGACY if self.root.resolve() == DEFAULT.resolve() else None

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / 'write.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def rows(self, kind):
        require(kind in KINDS, 'Unknown record kind')
        roots = ([self.legacy] if self.legacy else []) + [self.root]
        values = {}
        for root in roots:
            for path in (root / kind).glob('*.json'):
                row = json.loads(path.read_text())
                require(row['id'] not in values or row == values[row['id']], 'Conflicting historical record')
                values[row['id']] = row
        return sorted(values.values(),
                      key=lambda r: (r.get('recorded_at', ''), r['id']))

    def get(self, kind, key):
        require(kind in KINDS and isinstance(key, str) and re.fullmatch(r'[\w-]+', key), 'Invalid record id')
        path = self.root / kind / (key + '.json')
        if not path.is_file() and self.legacy:
            path = self.legacy / kind / (key + '.json')
        require(path.is_file(), 'Unknown ' + kind + ' record')
        return json.loads(path.read_text())

    def _append(self, kind, value):
        # Atomic visibility to readers; all writers hold the store lock.
        require(kind in KINDS and re.fullmatch(r'[\w-]+', value['id']), 'Invalid record')
        directory = self.root / kind
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (value['id'] + '.json')
        if path.exists():
            old = json.loads(path.read_text())
            require(old == value, 'Immutable record collision')
            return old
        temp = directory / (value['id'] + '.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        temp.replace(path)
        return value

    def append(self, kind, value):
        with self.locked():
            return self._append(kind, value)

    def source(self, source):
        require(isinstance(source.get('original_text'), str) and source['original_text'].strip(), 'Original source required')
        published, captured = source.get('published_at'), source.get('fetched_at') or source.get('snapshot_at')
        if published:
            time(published)
        if captured:
            time(captured)
        value = {**source, 'source_hash': digest(source['original_text'])}
        value['original_id'] = source['id']
        value['id'] = 'source-' + digest(source)[:24]
        value['known_at'] = max([t for t in (published, captured) if t], key=time) if captured else None
        value['source_hygiene'] = annotate(value)
        value['relationship'] = {
            'author': source.get('author_name'), 'author_id': source.get('author_id'),
            'publication': source.get('publication'), 'platform': source.get('platform'),
            'reply_to': source.get('reply_to'), 'quoted_post': source.get('quoted_post'),
            'thread_id': source.get('thread_id'), 'post_type': source.get('post_type'),
            'context_status': source.get('context_status', 'unresolved' if source.get('reply_to') or source.get('media_dependencies') else 'standalone_or_unknown')}
        value['missing_fields'] = [k for k in ('author_id', 'published_at', 'fetched_at', 'engagement_snapshot') if not source.get(k)]
        return self.append('sources', value)

    def event(self, event):
        allowed = {'family', 'title', 'mode', 'occurred_at', 'as_of', 'source_ids', 'evidence',
                   'research_source_ids', 'market_context', 'coverage', 'blocking_gaps', 'reassessment_of'}
        require(set(event) <= allowed, 'Unknown event fields: put market facts in dated evidence, not opaque context')
        require(event.get('family') and event.get('title') and event.get('mode') in ('replay', 'current', 'evergreen'), 'Event identity/mode required')
        cutoff = time(event['as_of'])
        require(cutoff <= time(now()), 'Event as-of cannot be in the future')
        require(time(event['occurred_at']) <= cutoff, 'Future event')
        require(isinstance(event.get('source_ids'), list), 'Event sources required')
        for sid in event['source_ids'] + event.get('research_source_ids', []):
            self.get('sources', sid)
        ids = set()
        for evidence in event.get('evidence', []):
            require(evidence['id'] not in ids, 'Duplicate evidence id')
            ids.add(evidence['id'])
            source = self.get('sources', evidence['source_id'])
            require(evidence['source_id'] in event['source_ids'], 'Evidence source absent from event source IDs')
            require(evidence.get('role') in ('primary', 'reported_claim', 'historical_framework', 'market_observation'), 'Evidence role required')
            require(evidence.get('quote') and evidence['quote'] in source['original_text'], 'Evidence quote must be exact')
            require(source.get('known_at'), 'Capture time missing; cannot claim as-of availability')
            require(time(source['known_at']) <= time(evidence['known_at']) <= cutoff, 'Future or backdated evidence')
            require(evidence.get('claim') and evidence.get('period'), 'Evidence claim and period required')
        context = event.get('market_context', [])
        require(isinstance(context, list) and all(isinstance(item, str) and item in ids for item in context),
                'Market context must reference admitted, time-checked evidence IDs')
        value = {**event, 'id': 'event-' + digest(event)[:24]}
        require(not any(e['family'] == event['family'] and time(e['as_of']) == cutoff and e['id'] != value['id']
                        for e in self.rows('events')), 'Conflicting event versions at the same as-of; use a new cutoff')
        return self.append('events', value)

    def latest_event(self, family):
        rows = [e for e in self.rows('events') if e['family'] == family]
        return max(rows, key=lambda e: (time(e['as_of']), e['id'])) if rows else None

    def review_research(self, unit_id, treatment, reviewer, reason, supporting_event_id=None):
        units = [u for r in self.rows('research') for u in r['units'] if u['id'] == unit_id]
        require(len(units) == 1, 'Unknown research unit')
        require(treatment in ('research', 'attribute', 'omit', 'needs_context') and reviewer.strip() and reason.strip(),
                'Human research treatment and reason required')
        support = self.get('events', supporting_event_id) if supporting_event_id else None
        if units[0]['treatment'] == 'needs_context' and treatment in ('research', 'attribute'):
            require(support and support['evidence'], 'Resolving missing context needs a supporting evidence event')
        return self.append('research_reviews', {'id': 'unit-review-' + uuid.uuid4().hex, 'recorded_at': now(),
            'unit_id': unit_id, 'source_id': units[0]['source_id'], 'treatment': treatment,
            'reviewer': reviewer, 'reason': reason, 'supporting_event_id': supporting_event_id,
            'label_source': 'human', 'belief_adopted': False})

    def propose(self, account_id, kind, topic, text, evidence_refs, origin):
        account(account_id)
        require(kind in STATE_KINDS and all(isinstance(x, str) and x.strip() for x in (topic, text, origin)), 'State kind/topic/text/origin required')
        require(isinstance(evidence_refs, list) and evidence_refs, 'State proposal evidence required')
        for ref in evidence_refs:
            self.get(ref['kind'], ref['id'])
        return self.append('state_proposals', {'id': 'proposal-' + uuid.uuid4().hex, 'recorded_at': now(),
            'account_id': account_id, 'kind': kind, 'topic': topic, 'text': text,
            'evidence_refs': evidence_refs, 'origin': origin, 'status': 'proposed'})

    def state_action(self, proposal_id, action, reviewer, reason, supersedes=None):
        require(action in ('adopt', 'reject', 'retract') and reviewer.strip() and reason.strip(), 'Human state decision and reason required')
        with self.locked():
            proposal = self.get('state_proposals', proposal_id)
            snapshot = self.snapshot(proposal['account_id'])
            active = {r['id'] for r in snapshot['adopted']}
            require((proposal_id in active) == (action == 'retract'), 'Adopt/reject only inactive proposals; retract only active state')
            if supersedes:
                require(action == 'adopt' and supersedes in active, 'Revision must supersede an active state of the same account')
            return self._append('state_actions', {'id': 'state-' + uuid.uuid4().hex, 'recorded_at': now(),
                'effective_at': now(), 'proposal_id': proposal_id, 'account_id': proposal['account_id'],
                'action': action, 'reviewer': reviewer, 'reviewer_identity': 'self_reported_human',
                'reason': reason, 'supersedes': supersedes})

    def snapshot(self, account_id, as_of=None):
        charter = account(account_id)
        cutoff = time(as_of or now())
        active = {}
        history = [a for a in self.rows('state_actions') if a['account_id'] == account_id
                   and time(a['recorded_at']) <= cutoff and time(a['effective_at']) <= cutoff]
        for action in history:
            key = action['proposal_id']
            if action['action'] == 'adopt':
                active[key] = self.get('state_proposals', key)
                if action.get('supersedes'):
                    active.pop(action['supersedes'], None)
            else:
                active.pop(key, None)
        adopted = list(active.values())
        return {'charter': charter, 'adopted': adopted, 'history': history,
                'cold_start': not history, 'version': digest([charter, adopted, history])}

    def feedback_context(self, account_id, as_of):
        rows = [r for kind in ('decision_feedback', 'reviews') for r in self.rows(kind)
                if r['account_id'] == account_id and time(r['recorded_at']) <= time(as_of)]
        rows.sort(key=lambda r: r['recorded_at'])
        result = rows[-12:]
        for publication in self.rows('publications'):
            if publication['account_id'] != account_id or time(publication['recorded_at']) > time(as_of):
                continue
            observations = [r for r in self.rows('engagement') if r['publication_id'] == publication['id']
                and time(r['recorded_at']) <= time(as_of) and time(r['observed_at']) <= time(as_of)]
            if observations:
                result.append({'id': publication['id'], 'kind': 'publication_performance',
                    'publication': publication, 'observations': observations[-3:],
                    'interpretation': 'Observed performance, not causal evidence of quality or permission to intensify claims.'})
        return result[-20:]

    def candidate(self, run_id, candidate_id):
        run = self.get('runs', run_id)
        rows = [c for c in run.get('candidates', []) if c['id'] == candidate_id]
        require(len(rows) == 1, 'Unknown candidate')
        return run, rows[0]

    def current(self, run):
        latest = self.latest_event(run['event']['family'])
        current = (self.snapshot(run['account_id'])['version'] == run['state']['version']
                   and latest['id'] == run['event']['id'])
        if current and run.get('pipeline') == 'account_source':
            from live.account_sources import valid_candidate
            try:
                valid_candidate(self, run['account_id'], run['inbox_candidate_id'])
            except ValueError:
                return False
        return current

    def decision_feedback(self, run_id, decision, reviewer, reason):
        require(decision in ('speak', 'wait', 'ignore') and reviewer.strip() and reason.strip(), 'Explicit human decision/reason required')
        run = self.get('runs', run_id)
        return self.append('decision_feedback', {'id': 'choice-' + uuid.uuid4().hex, 'recorded_at': now(),
            'run_id': run_id, 'event_id': run['event']['id'], 'event_title': run['event']['title'],
            'account_id': run['account_id'], 'machine_decision': run.get('decision', {}).get('action'),
            'decision': decision, 'reviewer': reviewer, 'reason': reason, 'label_source': 'human'})

    def human_allows_speech(self, run_id):
        rows = [r for r in self.rows('decision_feedback') if r['run_id'] == run_id]
        return not rows or rows[-1]['decision'] == 'speak'

    def review(self, run_id, candidate_id, expected_version, text, decision, reviewer, reason,
               dimensions=None, risk_note='', edit_class=None, error_types=None, issue_annotations=None):
        require(decision in ('approve', 'reject', 'save') and reviewer.strip() and reason.strip(), 'Human review and reason required')
        require(isinstance(text, str) and (text.strip() or decision == 'reject'), 'Empty draft')
        dimensions = dimensions or {}
        require(set(dimensions) <= {'native_language', 'useful_examples', 'rhythm_reasoning', 'account_fit', 'angle_value'}, 'Unknown editorial dimension')
        require(all(v in ('pass', 'fail', 'uncertain') for v in dimensions.values()), 'Invalid editorial rating')
        with self.locked():
            run, candidate = self.candidate(run_id, candidate_id)
            require(expected_version == digest(candidate['text']), 'Stale candidate version')
            risks = copy_risks(self, run, text, as_of=now())
            changed = text != candidate['text']
            classes = {'unchanged', 'minor', 'major', 'reject'}
            error_types = error_types or []
            require(isinstance(error_types, list) and all(isinstance(t, str) and t.strip() for t in error_types), 'Invalid error types')
            require(isinstance(issue_annotations or [], list), 'Issue annotations must be a list')
            annotations = []
            for annotation in issue_annotations or []:
                require(isinstance(annotation, dict), 'Invalid human issue annotation')
                category, note = annotation.get('category'), annotation.get('note')
                severity, quote = annotation.get('severity', 'unspecified'), annotation.get('quote', '')
                require(isinstance(category, str) and category.strip() and isinstance(note, str) and note.strip(),
                        'Human annotation category and note required')
                require(severity in {'minor', 'major', 'critical', 'unspecified'}, 'Invalid human issue severity')
                require(isinstance(quote, str), 'Annotation quote must be text')
                require(not quote or candidate['text'].count(quote) == 1,
                        'Annotation quote must match the original draft exactly and unambiguously')
                start = candidate['text'].find(quote) if quote else None
                annotations.append({'category': category.strip(), 'severity': severity, 'quote': quote,
                                    'note': note.strip(), 'original_start': start,
                                    'original_end': start + len(quote) if quote else None,
                                    'label_source': 'human'})
            if run.get('pipeline') == 'account_source' and decision != 'save':
                require(edit_class in classes, 'Explicit human edit class required')
            require(edit_class is None or edit_class in classes, 'Invalid edit class')
            require(edit_class != 'unchanged' or not changed, 'Changed text cannot be marked unchanged')
            require(edit_class not in ('minor', 'major') or changed, 'Edit class requires actual edits')
            require(decision != 'approve' or edit_class != 'reject', 'Approval contradicts reject class')
            require(decision != 'reject' or edit_class in (None, 'reject'), 'Rejection needs reject class')
            edits = [{'operation': op, 'original_start': i, 'original_end': j,
                      'edited_start': a, 'edited_end': b,
                      'before': candidate['text'][i:j], 'after': text[a:b]}
                     for op, i, j, a, b in SequenceMatcher(a=candidate['text'], b=text, autojunk=False).get_opcodes()
                     if op != 'equal']
            if decision == 'approve':
                require(self.current(run), 'State/evidence changed; rerun before approving')
                require(self.human_allows_speech(run_id), 'Human event decision is wait/ignore; change that decision before approving a post')
                require(set(dimensions) == {'native_language', 'useful_examples', 'rhythm_reasoning', 'account_fit', 'angle_value'}
                        and set(dimensions.values()) == {'pass'}, 'All editorial ratings must pass for approval')
                require(not (risks or changed or not candidate.get('machine_fidelity_pass')) or risk_note.strip(), 'Edited or machine-held copy needs an explicit human verification note')
            return self._append('reviews', {'id': 'review-' + uuid.uuid4().hex, 'recorded_at': now(),
                'run_id': run_id, 'candidate_id': candidate_id, 'account_id': run['account_id'],
                'event_id': run['event']['id'], 'event_title': run['event']['title'],
                'original_text': candidate['text'], 'text': text, 'text_hash': digest(text),
                'state_version': run['state']['version'], 'decision': decision, 'reviewer': reviewer,
                'reason': reason, 'dimensions': dimensions, 'risk_note': risk_note, 'risks': risks,
                'edit_class': edit_class, 'error_types': error_types, 'edit_spans': edits,
                'issue_annotations': annotations,
                'edit_distance': 1 - SequenceMatcher(a=candidate['text'], b=text, autojunk=False).ratio(),
                'machine_qa_applies_to_text': not changed, 'label_source': 'human',
                'reviewer_identity': 'self_reported_human', 'belief_adopted': False})

    def human_quality(self):
        """First actual draft and its first human verdict; failures never consume baseline."""
        runs = [r for r in self.rows('runs') if r.get('pipeline') == 'account_source']
        reviews = self.rows('reviews')
        groups, splits, first_candidates, baseline_by_run = {}, {}, {}, {}
        baseline_runs = []

        def counters(**identity):
            return {**identity, 'generated': 0, 'reviewed': 0, 'pending': 0,
                    'unchanged': 0, 'minor': 0, 'major': 0, 'reject': 0, 'unclassified': 0,
                    'execution_failed': 0, 'no_draft': 0, 'machine_pass': 0, 'followup_drafts': 0,
                    'error_counts': {}, 'human_severity_counts': {}, 'error_severity_counts': {},
                    'review_coverage': None, 'ready_with_at_most_minor_rate': None}

        def verdict_count(row, candidate, run):
            row['generated'] += 1
            row['machine_pass'] += bool(candidate.get('machine_fidelity_pass'))
            verdicts = [review for review in reviews if review['run_id'] == run['id']
                        and review['candidate_id'] == candidate['id']
                        and review['decision'] in ('approve', 'reject') and review.get('label_source') == 'human']
            if not verdicts:
                row['pending'] += 1
                return
            first = verdicts[0]
            row['reviewed'] += 1
            row[first.get('edit_class') or 'unclassified'] += 1
            annotations = [a for a in first.get('issue_annotations', []) if a.get('label_source') == 'human']
            categories = set(first.get('error_types', [])) | {a['category'] for a in annotations}
            for category in categories:
                row['error_counts'][category] = row['error_counts'].get(category, 0) + 1
            for severity in {a['severity'] for a in annotations if a.get('severity') != 'unspecified'}:
                row['human_severity_counts'][severity] = row['human_severity_counts'].get(severity, 0) + 1
            for category, severity in {(a['category'], a['severity']) for a in annotations}:
                bucket = row['error_severity_counts'].setdefault(category, {})
                bucket[severity] = bucket.get(severity, 0) + 1

        for run in runs:
            origin = run.get('generation_origin') or 'automated_pipeline'
            key = (run['account_id'], run.get('batch_id', 'unbatched'), origin)
            identity = {'account_id': key[0], 'batch_id': key[1], 'generation_origin': origin}
            row = groups.setdefault(key, counters(**identity))
            candidates = [c for c in run.get('candidates', []) if isinstance(c.get('text'), str) and c['text'].strip()]
            row['execution_failed'] += run['status'] == 'execution_failed'
            row['no_draft'] += not candidates
            candidate_group = (key, run.get('inbox_candidate_id', run['id']))
            # An explicit retry of an existing draft remains a follow-up even if its
            # inbox version/batch changes. Failed ancestors with no text do not qualify.
            baseline = baseline_by_run.get((origin, run.get('follow_up_of'))) or first_candidates.get(candidate_group)
            if not candidates:
                baseline_by_run[(origin, run['id'])] = baseline
                continue
            if baseline:
                row['followup_drafts'] += len(candidates)
                baseline_by_run[(origin, run['id'])] = baseline
                first_candidates.setdefault(candidate_group, baseline)
                continue
            first_candidates[candidate_group] = run['id']
            baseline_by_run[(origin, run['id'])] = run['id']
            baseline_runs.append(run['id'])
            for candidate in candidates:
                verdict_count(row, candidate, run)
                language = run.get('target_language') or 'unknown'
                length = 'short' if len(candidate['text']) <= 1000 else 'long'
                split_key = (*key, language, length)
                split = splits.setdefault(split_key, counters(**identity, target_language=language, length_bucket=length))
                verdict_count(split, candidate, run)
        for row in [*groups.values(), *splits.values()]:
            if row['generated']:
                row['review_coverage'] = row['reviewed'] / row['generated']
            if row['reviewed']:
                row['ready_with_at_most_minor_rate'] = (row['unchanged'] + row['minor']) / row['reviewed']
        return {'groups': list(groups.values()), 'splits': list(splits.values()), 'baseline_run_ids': baseline_runs,
                'basis': 'First actual draft per account/batch/source lineage/origin; first completed actual human verdict only',
                'automated_origin': 'automated_pipeline',
                'origin_basis': 'Assisted drafts remain separate; their labels never enter automated-pipeline rates',
                'length_basis': 'Original generated draft Unicode code points: short <= 1000, long > 1000; not a quality label',
                'severity_basis': 'Explicit human annotations only; never derived from machine QA or edit distance',
                'blind_study_status': 'not_run', 'machine_pass_is_human_acceptance': False}

    def review_packet(self, account_id, batch_id=None):
        """Read-only exact review data, including holds; not a completed blind study."""
        account(account_id)
        quality = self.human_quality()
        baselines = set(quality['baseline_run_ids'])
        reviews = self.rows('reviews')
        entries = []
        for run in self.rows('runs'):
            if run.get('pipeline') != 'account_source' or run['account_id'] != account_id:
                continue
            if batch_id is not None and run.get('batch_id', 'unbatched') != batch_id:
                continue
            adaptation = run.get('source_adaptation') or {}
            entries.append({'run_id': run['id'], 'batch_id': run.get('batch_id', 'unbatched'),
                'fixture_id': run.get('fixture_id'), 'follow_up_of': run.get('follow_up_of'),
                'generation_origin': run.get('generation_origin') or 'automated_pipeline',
                'generation_protocol': run.get('generation_protocol'),
                'baseline': run['id'] in baselines, 'title': run['event']['title'],
                'mode': run['event']['mode'], 'as_of': run['event']['as_of'],
                'status': run['status'], 'target_language': run.get('target_language'),
                'sources': [self.get('sources', sid) for sid in run['event'].get('source_ids', [])],
                'selected_passages': (adaptation.get('selection') or {}).get('passages', []),
                'translation_text': (adaptation.get('translation') or {}).get('text', ''),
                'candidates': [{**c, 'human_reviews': [v for v in reviews
                              if v['run_id'] == run['id'] and v['candidate_id'] == c['id']]}
                               for c in run.get('candidates', [])]})
        return {'account_id': account_id, 'batch_id': batch_id, 'exported_at': now(),
                'entries': entries, 'human_quality': {k: v for k, v in quality.items()
                    if k not in {'groups', 'splits', 'baseline_run_ids'}} | {
                    'groups': [g for g in quality['groups'] if g['account_id'] == account_id
                               and (batch_id is None or g['batch_id'] == batch_id)],
                    'splits': [g for g in quality['splits'] if g['account_id'] == account_id
                               and (batch_id is None or g['batch_id'] == batch_id)]},
                'blind_study': {'status': 'not_run', 'real_reference_count': 0, 'human_rating_count': 0,
                    'purpose': 'Editorial naturalness and publishability, not author impersonation',
                    'missing': ['Matched, attributable real reference posts', 'Randomized participant packet with hidden answer key',
                                'Actual human naturalness/publishability/AI-likelihood ratings'],
                    'machine_scores_are_not_human_labels': True}}

    def publication(self, review_id, platform, post_id, published_at, text_hash, url=''):
        require(platform.strip() and post_id.strip(), 'Platform/post ID required')
        with self.locked():
            review = self.get('reviews', review_id)
            run = self.get('runs', review['run_id'])
            require(review['decision'] == 'approve' and review['text_hash'] == text_hash, 'Exact approved text required')
            require(time(review['recorded_at']) <= time(published_at) <= time(now()), 'Invalid publication timestamp')
            require(self.current(run), 'Evidence/account state changed; publication approval stale')
            require(self.human_allows_speech(run['id']), 'Human event decision currently stops publication linkage')
            recent = [r for r in self.rows('reviews') if r['candidate_id'] == review['candidate_id']]
            require(recent[-1]['id'] == review_id, 'A newer review supersedes this approval')
            value = {'id': 'publication-' + digest([review['account_id'], platform, post_id])[:24],
                'recorded_at': now(), 'review_id': review_id, 'account_id': review['account_id'],
                'platform': platform, 'post_id': post_id, 'published_at': published_at,
                'text_hash': text_hash, 'url': url, 'provenance': 'Human-reported linkage, not remotely verified',
                'belief_adopted': False}
            return self._append('publications', value)

    def engagement(self, publication_id, observed_at, metrics, provenance):
        publication = self.get('publications', publication_id)
        require(time(publication['published_at']) <= time(observed_at) <= time(now()), 'Invalid metric time')
        require(metrics and all(isinstance(k, str) and type(v) in (int, float) and math.isfinite(v) and v >= 0 for k, v in metrics.items()), 'Nonnegative finite metrics required')
        require(provenance.strip(), 'Metric provenance required')
        return self.append('engagement', {'id': 'engagement-' + uuid.uuid4().hex, 'recorded_at': now(),
            'account_id': publication['account_id'], 'publication_id': publication_id,
            'observed_at': observed_at, 'metrics': metrics, 'provenance': provenance})

    def learning_export(self):
        rows = []
        for kind in ('decision_feedback', 'reviews'):
            for row in self.rows(kind):
                if row.get('label_source') != 'human' or row.get('decision') == 'save':
                    continue
                run = self.get('runs', row['run_id'])
                rows.append({'label_id': row['id'], 'labelled_at': row['recorded_at'],
                    'split_group': run['event']['family'], 'source_groups': run['event'].get('source_ids', []),
                    'event_as_of': run['event']['as_of'], 'input': {'event': run['event'], 'state': run['state']},
                    'label': row, 'task': 'event_decision' if kind == 'decision_feedback' else 'candidate_review'})
        return {'rows': sorted(rows, key=lambda r: (r['event_as_of'], r['labelled_at'])),
            'training_enabled': False, 'split_policy': 'Chronological by event_as_of, grouping shared event/source families; do not randomly split candidates.'}

    def feedback_summary(self):
        reviews = self.rows('reviews')
        failures = Counter(k for r in reviews for k, v in r.get('dimensions', {}).items() if v == 'fail')
        return {'human_reviews': len(reviews), 'explicit_event_labels': len(self.rows('decision_feedback')),
            'research_reviews': len(self.rows('research_reviews')),
            'repeated_editorial_failures': dict(failures), 'publications': len(self.rows('publications')),
            'engagement_snapshots': len(self.rows('engagement')), 'automatic_training': False,
            'automatic_belief_updates': False, 'performance_causality': 'Unknown; no controlled or sufficient longitudinal evidence'}


def copy_risks(store, run, text, as_of=None):
    findings = []
    for sid in run['event'].get('source_ids', []):
        source = store.get('sources', sid)
        guidance = json.dumps(run.get('decision') or {}, ensure_ascii=False)
        result = postcheck(source, text, guidance, [], as_of=as_of or run['event']['as_of'])
        findings += [{**f, 'source_id': sid} for f in result['findings'] if f['level'] == 'review']
    if re.search(r'(?i)(?:absent from the source|unsupported by the source|constitute a new opinion|the source does not (?:provide|support)|QA (?:check|reasoning))|该来源没有提供|构成新的观点|不能自动形成因果关系|原文没有支持', text):
        findings.append({'kind': 'public_audit_language', 'level': 'review'})
    return findings
