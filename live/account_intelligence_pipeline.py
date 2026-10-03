"""Opt-in event + account state pipeline; existing relay, no production queue."""
from __future__ import annotations
import json
import re
import uuid
from live.account_intelligence import Store, account, accounts, require, time, copy_risks
from live.distillation_source import digest, now, detect_language
from live.distillation_client import RelayClient
from live.model_json import parse_object
from live.numeric_fidelity import inventory
from live import account_intelligence_prompts as prompts

CHECKS = {'supported_claims', 'numeric_entity_consistency', 'identity_boundary',
          'temporal_accuracy', 'adopted_stance_consistency', 'source_hygiene', 'silent_qa'}


class Pipeline:
    def __init__(self, store=None, client=None):
        self.store = store or Store()
        self.client = client or RelayClient(self.store.root.parent / 'calls')

    def ask(self, stage, system, payload, max_tokens=3200):
        response = self.client(stage, [{'role': 'system', 'content': system},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}], max_tokens)
        require(response.get('finish_reason') == 'stop' and not response.get('refusal'), stage + ': incomplete model response')
        return parse_object(response.get('text', ''))

    def research(self, source_id):
        source = self.store.get('sources', source_id)
        key = 'research-' + digest([source, prompts.VERSION])[:24]
        old = [r for r in self.store.rows('research') if r['id'] == key]
        if old:
            return old[0]
        raw = self.ask('owned_research', prompts.RESEARCH, {'source': source}, 5000)
        require(isinstance(raw.get('units'), list) and raw['units'], 'Research units required')
        units = []
        for unit in raw['units']:
            quote = unit.get('quote')
            require(isinstance(quote, str) and quote.strip() and quote in source['original_text'], 'Research quote must be exact')
            require(source['original_text'].count(quote) == 1, 'Ambiguous research quote; use more surrounding text')
            start = source['original_text'].index(quote)
            require(unit.get('durability') in ('durable', 'transient', 'mixed', 'unknown'), 'Invalid durability')
            require(unit.get('identity') in ('transferable', 'personal', 'mixed', 'quoted', 'unknown'), 'Invalid identity classification')
            require(unit.get('treatment') in ('research', 'attribute', 'omit', 'needs_context'), 'Invalid research treatment')
            require(type(unit.get('confidence')) in (float, int) and 0 <= unit['confidence'] <= 1, 'Invalid confidence')
            require(unit.get('reason') and unit.get('topics') and unit.get('behavior'), 'Incomplete research annotation')
            require(unit['behavior'] in ('framework', 'news_reaction', 'position_disclosure', 'prediction', 'review', 'education', 'interaction', 'promotion', 'other'), 'Invalid behavior')
            require(isinstance(unit['topics'], list) and all(isinstance(t, str) for t in unit['topics']), 'Invalid research topics')
            units.append({**unit, 'id': 'unit-' + digest([source_id, start, quote, prompts.VERSION])[:20],
                'source_id': source_id, 'start': start, 'end': start + len(quote),
                'known_at': source.get('known_at'), 'source_date': source.get('published_at'),
                'human_status': 'pending', 'confidence_basis': 'uncalibrated_model_estimate'})
        require(len({u['id'] for u in units}) == len(units), 'Duplicate research unit')
        return self.store.append('research', {'id': key, 'recorded_at': now(), 'source_id': source_id,
            'prompt_version': prompts.VERSION, 'units': units, 'human_status': 'pending',
            'observable_style': {'characters': len(source['original_text']),
                'paragraphs': len(re.split(r'\n\s*\n', source['original_text'])),
                'newlines': source['original_text'].count('\n')},
            'event_alignment': 'Unknown unless explicitly evidenced in unit; not inferred from chronology alone',
            'archive_silence': 'Unknown; source coverage is incomplete'})

    def available_research(self, event):
        allowed = set(event.get('source_ids', [])) | set(event.get('research_source_ids', []))
        units = [unit for row in self.store.rows('research') for unit in row['units']
            if unit['source_id'] in allowed and unit.get('known_at')
            and time(unit['known_at']) <= time(event['as_of'])]
        for unit in units:
            reviews = [r for r in self.store.rows('research_reviews') if r['unit_id'] == unit['id']
                       and time(r['recorded_at']) <= time(event['as_of'])]
            if not reviews:
                continue
            review = reviews[-1]
            support = self.store.get('events', review['supporting_event_id']) if review.get('supporting_event_id') else None
            if support:
                # Supporting context must itself be in the generation packet, not
                # merely known to a human or available somewhere in the archive.
                supplied = {digest(e) for e in event.get('evidence', [])}
                if time(support['as_of']) > time(event['as_of']) or not {digest(e) for e in support['evidence']} <= supplied:
                    unit['review_not_applied'] = 'Supporting evidence is absent from this event snapshot'
                    continue
            unit.update(model_treatment=unit['treatment'], treatment=review['treatment'],
                        human_status='reviewed', human_review=review)
        return units

    def run(self, event_id, account_id, follow_up_of=None):
        call_start = len(getattr(self.client, 'calls', []))
        event = self.store.get('events', event_id)
        state = self.store.snapshot(account_id, event['as_of'])
        run = {'id': 'run-' + uuid.uuid4().hex, 'recorded_at': now(), 'event': event,
            'account_id': account_id, 'target_language': account(account_id)['language'], 'state': state,
            'prompt_version': prompts.VERSION, 'status': 'started', 'candidates': [], 'human_status': 'pending',
            'follow_up_of': follow_up_of, 'publishing_enabled': False}
        if follow_up_of:
            previous = self.store.get('runs', follow_up_of)
            require(previous['account_id'] == account_id and previous['event']['family'] == event['family'], 'Follow-up identity mismatch')
        try:
            self._run(run)
        except Exception as exc:
            # Relay error details (sanitized there) live in logged calls, not public UI.
            run.update(status='execution_failed', error_type=type(exc).__name__)
            if isinstance(exc, ValueError):
                run['contract_error'] = str(exc)[:240]
        run['finished_at'] = now()
        run['runtime_version'] = 'owned-runner-v1.0.1'
        run['call_refs'] = [ref for ref in getattr(self.client, 'calls', [])[call_start:]
                            if isinstance(ref, dict) and ref.get('path')]
        self.store.append('runs', run)
        return run

    def _run(self, run):
        event = run['event']
        sources = [self.store.get('sources', sid) for sid in event.get('source_ids', [])]
        blockers = list(event.get('blocking_gaps', []))
        for source in sources:
            if source.get('content_complete') is not True or source.get('media_dependencies') or source['relationship']['context_status'] == 'unresolved':
                blockers.append('Source context/extraction incomplete: ' + source['id'])
        if not event.get('evidence'):
            blockers.append('No exact, dated evidence admitted')
        if event['mode'] == 'current' and (time(now()) - time(event['as_of'])).total_seconds() > 48 * 3600:
            blockers.append('Current-mode event snapshot is stale; refresh evidence')
        if blockers:
            run.update(status='wait', decision={'action': 'wait', 'reason': '; '.join(blockers), 'missing_evidence': blockers, 'origin': 'preflight'})
            return
        research = self.available_research(event)
        feedback = self.store.feedback_context(run['account_id'], event['as_of'])
        context = {'event': event, 'account_state': run['state'], 'research': research,
            'human_feedback': feedback, 'source_relationships': [{k: s.get(k) for k in ('id', 'published_at', 'known_at', 'relationship', 'source_hygiene')} for s in sources]}
        run['feedback_ids'] = [r['id'] for r in feedback]
        decision = self.ask('owned_decision', prompts.DECIDE, context)
        run['decision'] = decision
        require(decision.get('action') in ('speak', 'wait', 'ignore'), 'Invalid editorial action')
        require(decision.get('reason'), 'Decision rationale required')
        for field, valid in [('evidence_ids', {e['id'] for e in event['evidence']}),
                             ('research_ids', {u['id'] for u in research}),
                             ('state_refs', {s['id'] for s in run['state']['adopted']})]:
            require(isinstance(decision.get(field), list) and set(decision[field]) <= valid, 'Unknown ' + field)
        require(decision.get('relation') in ('new', 'consistent', 'updates', 'conflicts', 'none'), 'Unknown state relationship')
        if decision['relation'] in ('consistent', 'updates', 'conflicts'):
            require(decision['state_refs'], 'Cannot claim an account history without adopted state')
        if decision['action'] != 'speak':
            run['status'] = decision['action']
            return
        require(decision['evidence_ids'] and decision.get('angle') and decision.get('value_beyond_translation'), 'Speak requires evidence and editorial value')
        require(decision.get('treatment') in ('original_commentary', 'framework_reactivation', 'source_adaptation'), 'Invalid treatment')
        chosen = [e for e in event['evidence'] if e['id'] in decision['evidence_ids']]
        chosen_research = [u for u in research if u['id'] in decision['research_ids']]
        require(not any(u['treatment'] in ('omit', 'needs_context') for u in chosen_research), 'Decision selected omitted/unresolved research')
        context.update(selected_evidence=chosen, selected_research=chosen_research, decision=decision)
        # Whole selected quotes and their full source context are first-class inputs.
        ids = {e['source_id'] for e in chosen} | {u['source_id'] for u in chosen_research}
        context['selected_sources'] = [self.store.get('sources', sid) for sid in sorted(ids)]
        run['selected_research'] = chosen_research
        raw = self.ask('owned_candidates', prompts.WRITE, context, 4200)
        require(isinstance(raw.get('candidates'), list) and len(raw['candidates']) == 2, 'Exactly two candidates required')
        for i, candidate in enumerate(raw['candidates']):
            require(isinstance(candidate.get('text'), str) and candidate['text'].strip(), 'Candidate text required')
            candidate.update(id=run['id'] + '-c' + str(i + 1), human_status='pending')
            require(candidate.get('claim_links'), 'Private claim bindings required')
            for link in candidate['claim_links']:
                require(link.get('quote') and link['quote'] in candidate['text'], 'Claim link must quote candidate exactly')
                require(link.get('evidence_ids') and set(link['evidence_ids']) <= set(decision['evidence_ids']), 'Invalid claim evidence link')
                require(link.get('kind') in ('fact', 'interpretation', 'framework'), 'Invalid claim kind')
            for use in candidate.get('research_use', []):
                require(use['unit_id'] in decision['research_ids'], 'Unselected research use')
            run['candidates'].append(candidate)
        require(raw['candidates'][0]['text'] != raw['candidates'][1]['text'], 'Duplicate candidates')
        qa = self.ask('owned_qa', prompts.QA, {**context, 'candidates': run['candidates']}, 4200)
        reviews = qa.get('reviews', [])
        require(len(reviews) == 2 and {r.get('candidate_id') for r in reviews} == {c['id'] for c in run['candidates']}, 'QA must cover both candidates')
        for candidate in run['candidates']:
            review = next(r for r in reviews if r['candidate_id'] == candidate['id'])
            require(set(review.get('fidelity', {})) == CHECKS and all(type(v) is bool for v in review['fidelity'].values()), 'Incomplete fidelity QA')
            require(isinstance(review.get('issues'), list) and isinstance(review.get('editorial'), dict), 'Incomplete review')
            require(all(isinstance(issue, dict) and issue.get('severity') in ('hold', 'note')
                        and issue.get('category') and issue.get('reason') for issue in review['issues']), 'Invalid QA issue severity/schema')
            candidate['machine_qa'] = review
            candidate['deterministic_risks'] = copy_risks(self.store, run, candidate['text'])
            # Novel quantities are a conservative review flag, not proof of semantic error.
            evidence_text = '\n'.join(e['quote'] + '\n' + e['claim'] + '\n' + e['period'] for e in chosen)
            seen = set(inventory(evidence_text))
            novel = set(inventory(candidate['text'])) - seen
            candidate['numeric_observations'] = [{'value': value, 'unit': unit, 'status': 'review_novel_quantity'} for value, unit in sorted(novel)]
            language, confidence = detect_language(candidate['text'])
            candidate['language_check'] = {'detected': language, 'expected': run['target_language'],
                'confidence': confidence, 'method': 'existing en/zh heuristic; not native-quality assessment'}
            wrong_language = language != 'unknown' and language != run['target_language']
            candidate['machine_fidelity_pass'] = (all(review['fidelity'].values())
                and not any(issue.get('severity') == 'hold' for issue in review['issues'])
                and not candidate['deterministic_risks'] and not novel and not wrong_language)
            candidate['editorial_quality'] = 'human_review_pending'
        run['status'] = 'candidates_ready' if all(c['machine_fidelity_pass'] for c in run['candidates']) else 'machine_hold'
        run['state_proposal_ids'] = []
        # Proposals are stored for review only; no automatic account-state adoption.
        for proposal in decision.get('proposed_state', []):
            saved = self.store.propose(run['account_id'], proposal['kind'], proposal['topic'], proposal['text'],
                [{'kind': 'events', 'id': event['id']}], 'model proposal from ' + run['id'])
            run['state_proposal_ids'].append(saved['id'])

    def event_all_accounts(self, event_id):
        raise ValueError('Event broadcast retired. Use an admitted account source candidate.')
