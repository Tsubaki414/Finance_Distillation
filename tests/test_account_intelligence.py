"""Contract tests use explicit test doubles, never labelled as real model outputs."""
import copy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from live.account_intelligence import Store, accounts, digest, now, copy_risks
from live.account_intelligence_pipeline import Pipeline, CHECKS
from backend import account_intelligence as api
from backend.content_dashboard import app


class ModelDouble:
    def __init__(self, action='speak', modify=None):
        self.calls = []
        self.action = action
        self.modify = modify

    def __call__(self, stage, messages, max_tokens):
        payload = json.loads(messages[-1]['content'])
        self.calls.append((stage, payload))
        if stage == 'owned_research':
            value = {'units': [{'quote': payload['source']['original_text'], 'behavior': 'framework',
                'topics': ['test'], 'insight': 'TEST ONLY', 'stance': 'TEST ONLY', 'confidence': .6,
                'durability': 'durable', 'identity': 'transferable', 'treatment': 'research',
                'reason': 'TEST ONLY', 'speaker': 'author', 'trigger': 'unknown', 'format': 'one sentence'}]}
        elif stage == 'owned_decision':
            value = {'action': self.action, 'reason': 'TEST ONLY explicit editorial decision',
                'angle': 'Read the reported result', 'stance': 'TEST ONLY', 'relation': 'new', 'state_refs': [],
                'evidence_ids': [payload['event']['evidence'][0]['id']], 'research_ids': [],
                'missing_evidence': [], 'treatment': 'original_commentary', 'value_beyond_translation': 'TEST ONLY',
                'identity_plan': 'No personal history', 'proposed_state': []}
        elif stage == 'owned_candidates':
            value = {'candidates': [{'text': text, 'format': 'TEST ONLY', 'claim_links': [
                {'quote': text, 'evidence_ids': ['fact'], 'kind': 'fact'}], 'research_use': []} for text in
                ['Revenue was $10 billion.', 'The reported revenue was $10 billion.']]}
        elif stage == 'owned_qa':
            value = {'reviews': [{'candidate_id': c['id'], 'fidelity': {key: True for key in CHECKS},
                'issues': [], 'editorial': {'native_language': 'review', 'notes': 'TEST DOUBLE; not human quality'}}
                for c in payload['candidates']]}
        else:
            raise AssertionError(stage)
        if self.modify:
            self.modify(stage, value, payload)
        return {'finish_reason': 'stop', 'text': json.dumps(value), 'model': 'TEST_DOUBLE'}


class IntelligenceCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.source = self.store.source({'id': 'test-source', 'original_text': 'Revenue was $10 billion.',
            'author_name': 'TEST issuer', 'published_at': '2026-01-01T00:00:00Z', 'fetched_at': '2026-01-02T00:00:00Z',
            'content_complete': True, 'media_dependencies': [], 'source_language': 'en', 'platform': 'web'})
        self.body = {'family': 'TEST-event', 'title': 'TEST revenue', 'mode': 'replay',
            'occurred_at': '2026-01-01T00:00:00Z', 'as_of': '2026-01-03T00:00:00Z',
            'source_ids': [self.source['id']], 'evidence': [{'id': 'fact', 'source_id': self.source['id'],
                'quote': self.source['original_text'], 'claim': 'Revenue $10 billion.', 'role': 'primary',
                'period': '2026 Q1', 'known_at': self.source['known_at']}]}
        self.event = self.store.event(self.body)
        self.model = ModelDouble()
        self.pipeline = Pipeline(self.store, self.model)

    def run_case(self):
        return self.pipeline.run(self.event['id'], 'en_industry')

    def proposal(self):
        return self.store.propose('en_industry', 'framework', 'Revenue', 'TEST framework',
            [{'kind': 'events', 'id': self.event['id']}], 'TEST ONLY')

    def approve(self, run):
        c = run['candidates'][0]
        return self.store.review(run['id'], c['id'], digest(c['text']), c['text'], 'approve', 'TEST HUMAN',
            'TEST ONLY approval', {k: 'pass' for k in ('native_language', 'useful_examples', 'rhythm_reasoning', 'account_fit', 'angle_value')})

    def test_five_charters_languages_and_original_owned_identity(self):
        self.assertEqual(len(accounts()), 5)
        self.assertEqual([a['language'] for a in accounts()], ['en', 'zh', 'en', 'zh', 'en'])
        self.assertTrue(all(a['platform'] == 'unbound' for a in accounts()))

    def test_source_immutable_provenance_annotations(self):
        self.assertEqual(self.store.get('sources', self.source['id'])['original_text'], self.source['original_text'])
        changed = {**self.source, 'original_text': 'tampered'}
        with self.assertRaisesRegex(ValueError, 'Immutable'):
            self.store.append('sources', changed)
        self.assertIn('relationship', self.source)
        self.assertIn('author_id', self.source['missing_fields'])

    def test_future_or_backdated_evidence_rejected(self):
        for asof, known in [('2026-01-01T12:00:00Z', '2026-01-02T00:00:00Z'),
                            ('2026-01-04T00:00:00Z', '2026-01-01T01:00:00Z')]:
            body = copy.deepcopy(self.body); body['as_of'] = asof; body['evidence'][0]['known_at'] = known
            with self.assertRaisesRegex(ValueError, 'Future or backdated'):
                self.store.event(body)

    def test_inexact_evidence_quote_rejected(self):
        body = copy.deepcopy(self.body); body['evidence'][0]['quote'] = 'Revenue was $11 billion.'
        with self.assertRaisesRegex(ValueError, 'quote'):
            self.store.event(body)

    def test_evidence_cannot_hide_source_from_hygiene(self):
        body = copy.deepcopy(self.body); body['source_ids'] = []
        with self.assertRaisesRegex(ValueError, 'absent'):
            self.store.event(body)

    def test_market_context_cannot_bypass_time_checked_evidence(self):
        for extra in ({'market_context': [{'price': 999, 'known_at': '2099-01-01T00:00:00Z'}]},
                      {'future_outcome': 'A later event nobody knew at as_of'}, {'market_context': ['missing']}):
            with self.assertRaises(ValueError):
                self.store.event({**self.body, **extra})
        event = self.store.event({**self.body, 'family': 'market-context-refs', 'market_context': ['fact']})
        self.assertEqual(event['market_context'], ['fact'])

    def test_conflicting_same_cutoff_versions_rejected(self):
        body = copy.deepcopy(self.body); body['title'] = 'Different'
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            self.store.event(body)

    def test_research_exact_offsets_and_not_adopted_memory(self):
        result = self.pipeline.research(self.source['id'])
        unit = result['units'][0]
        self.assertEqual(self.source['original_text'][unit['start']:unit['end']], unit['quote'])
        self.assertEqual(self.store.snapshot('en_industry')['adopted'], [])
        self.assertEqual(self.pipeline.research(self.source['id']), result)
        self.assertEqual(len(self.model.calls), 1)

    def test_research_invented_quote_rejected(self):
        self.model.modify = lambda stage, value, payload: value['units'][0].update(quote='Invented')
        with self.assertRaisesRegex(ValueError, 'exact'):
            self.pipeline.research(self.source['id'])

    def test_future_research_not_retrieved(self):
        self.pipeline.research(self.source['id'])
        event = {**self.event, 'as_of': '2026-01-01T12:00:00Z'}
        self.assertEqual(self.pipeline.available_research(event), [])

    def test_human_research_treatment_is_temporal_and_not_belief_adoption(self):
        row = self.pipeline.research(self.source['id']); unit = row['units'][0]
        self.store.review_research(unit['id'], 'omit', 'TEST HUMAN', 'Personal detail is unnecessary')
        self.assertEqual(self.pipeline.available_research(self.event)[0]['treatment'], 'research')
        present = {**self.event, 'as_of': now()}
        self.assertEqual(self.pipeline.available_research(present)[0]['treatment'], 'omit')
        self.assertEqual(self.store.snapshot('en_industry')['adopted'], [])
        self.assertEqual(self.store.get('research', row['id'])['units'][0]['treatment'], 'research')

    def test_context_resolution_requires_actual_evidence_in_writer_packet(self):
        self.model.modify = lambda stage, value, payload: value['units'][0].update(treatment='needs_context')
        unit = self.pipeline.research(self.source['id'])['units'][0]
        with self.assertRaisesRegex(ValueError, 'supporting evidence'):
            self.store.review_research(unit['id'], 'research', 'TEST', 'Resolved')
        self.store.review_research(unit['id'], 'research', 'TEST', 'Supported by the event evidence', self.event['id'])
        current = {**self.event, 'as_of': now()}
        self.assertEqual(self.pipeline.available_research(current)[0]['treatment'], 'research')
        missing = {**current, 'evidence': []}
        self.assertEqual(self.pipeline.available_research(missing)[0]['treatment'], 'needs_context')

    def test_speak_two_candidates_machine_not_human_or_belief(self):
        run = self.run_case()
        self.assertEqual(run['status'], 'candidates_ready')
        self.assertEqual(len(run['candidates']), 2)
        self.assertEqual(run['human_status'], 'pending')
        self.assertTrue(run['candidates'][0]['machine_fidelity_pass'])
        self.assertEqual(run['candidates'][0]['editorial_quality'], 'human_review_pending')
        self.assertEqual(self.store.snapshot('en_industry')['adopted'], [])
        self.assertEqual(self.store.learning_export()['rows'], [])

    def test_ignore_and_wait_never_call_writer(self):
        for action in ('ignore', 'wait'):
            model = ModelDouble(action)
            run = Pipeline(self.store, model).run(self.event['id'], 'zh_macro')
            self.assertEqual(run['status'], action)
            self.assertEqual([s for s, _ in model.calls], ['owned_decision'])
            self.assertEqual(run['candidates'], [])

    def test_no_evidence_waits_without_model_call(self):
        body = {**self.body, 'family': 'no-evidence', 'evidence': []}
        event = self.store.event(body)
        run = self.pipeline.run(event['id'], 'en_industry')
        self.assertEqual(run['status'], 'wait'); self.assertEqual(self.model.calls, [])

    def test_incomplete_media_waits(self):
        source = self.store.source({**self.source, 'id': 'media', 'media_dependencies': ['missing chart']})
        body = copy.deepcopy(self.body); body.update(family='media', source_ids=[source['id']]); body['evidence'][0]['source_id'] = source['id']
        run = self.pipeline.run(self.store.event(body)['id'], 'en_industry')
        self.assertEqual(run['status'], 'wait'); self.assertEqual(self.model.calls, [])

    def test_stale_current_snapshot_stops(self):
        event = self.store.event({**self.body, 'family': 'stale', 'mode': 'current'})
        run = self.pipeline.run(event['id'], 'en_industry')
        self.assertEqual(run['status'], 'wait'); self.assertEqual(self.model.calls, [])

    def test_account_language_not_source_language(self):
        run = self.pipeline.run(self.event['id'], 'zh_industry')
        self.assertEqual(run['target_language'], 'zh')
        payload = next(p for s, p in self.model.calls if s == 'owned_candidates')
        self.assertEqual(payload['account_state']['charter']['language'], 'zh')
        self.assertEqual(payload['selected_sources'][0]['original_text'], self.source['original_text'])

    def test_unknown_evidence_and_fake_memory_fail_closed(self):
        for key, change in [('evidence_ids', ['invented']), ('relation', 'consistent')]:
            model = ModelDouble(modify=lambda s, v, p: v.update({key: change}) if s == 'owned_decision' else None)
            run = Pipeline(self.store, model).run(self.event['id'], 'en_industry')
            self.assertEqual(run['status'], 'execution_failed')
            self.assertEqual(len(model.calls), 1)

    def test_new_numbers_are_held_even_if_llm_passes(self):
        def change(stage, value, payload):
            if stage == 'owned_candidates':
                for c in value['candidates']:
                    c['text'] = c['text'].replace('$10', '$11'); c['claim_links'][0]['quote'] = c['text']
        self.model.modify = change
        run = self.run_case()
        self.assertEqual(run['status'], 'machine_hold')
        self.assertTrue(run['candidates'][0]['numeric_observations'])

    def test_wrong_output_language_is_held_even_if_model_qa_passes(self):
        def change(stage, value, payload):
            if stage == 'owned_candidates':
                for candidate, text in zip(value['candidates'], ['这家公司的收入数据在公告中披露。', '这家公司的收入数据已经正式公布了。']):
                    candidate['text'] = text; candidate['claim_links'][0]['quote'] = text
        self.model.modify = change
        run = self.run_case()
        self.assertEqual(run['status'], 'machine_hold')
        self.assertEqual(run['candidates'][0]['language_check']['detected'], 'zh')

    def test_unrecognized_qa_severity_cannot_silently_pass(self):
        def change(stage, value, payload):
            if stage == 'owned_qa':
                value['reviews'][0]['issues'] = [{'category': 'fact', 'severity': 'not_a_supported_level', 'reason': 'TEST'}]
        self.model.modify = change
        run = self.run_case()
        self.assertEqual(run['status'], 'execution_failed')
        self.assertEqual(len(run['candidates']), 2)

    def test_public_qa_language_is_flagged(self):
        run = self.run_case()
        self.assertTrue(copy_risks(self.store, run, '该来源没有提供更多细节。'))

    def test_identity_check_reads_guidance_beyond_angle(self):
        personal = self.store.source({**self.source, 'id': 'personal', 'original_text': 'My holdings include ALAB.'})
        run = {'event': {'source_ids': [personal['id']], 'as_of': self.event['as_of']},
               'decision': {'angle': 'Connectivity framework', 'identity_plan': 'Keep first person throughout.'}}
        self.assertTrue(any(r.get('code') == 'guidance_identity_boundary' for r in copy_risks(self.store, run, 'Connectivity matters.')))

    def test_historical_replay_time_is_rechecked_at_human_review(self):
        run = self.run_case(); c = run['candidates'][0]
        review = self.store.review(run['id'], c['id'], digest(c['text']), 'Revenue was reported today.',
            'save', 'TEST HUMAN', 'Review an old draft in the present')
        self.assertTrue(any(r.get('code') == 'stale_time_reference' for r in review['risks']))

    def test_missing_qa_keeps_failed_output(self):
        self.model.modify = lambda stage, value, payload: value['reviews'].pop() if stage == 'owned_qa' else None
        run = self.run_case()
        self.assertEqual(run['status'], 'execution_failed')
        self.assertEqual(len(run['candidates']), 2)

    def test_proposals_do_not_change_state_until_human_adopts(self):
        before = self.store.snapshot('en_industry')
        proposal = self.proposal()
        self.assertEqual(before['version'], self.store.snapshot('en_industry')['version'])
        self.store.state_action(proposal['id'], 'adopt', 'TEST HUMAN', 'TEST reason')
        after = self.store.snapshot('en_industry')
        self.assertNotEqual(before['version'], after['version'])
        self.assertEqual(len(after['adopted']), 1)
        self.assertEqual(self.store.snapshot('en_industry', '2026-01-03T00:00:00Z')['adopted'], [])

    def test_state_revision_retraction_and_wrong_account_supersede(self):
        old = self.proposal(); self.store.state_action(old['id'], 'adopt', 'TEST', 'reason')
        new = self.proposal(); self.store.state_action(new['id'], 'adopt', 'TEST', 'revision', old['id'])
        self.assertEqual([r['id'] for r in self.store.snapshot('en_industry')['adopted']], [new['id']])
        self.store.state_action(new['id'], 'retract', 'TEST', 'counter evidence')
        self.assertEqual(self.store.snapshot('en_industry')['adopted'], [])
        other = self.store.propose('zh_macro', 'view', 'TEST', 'TEST', [{'kind': 'events', 'id': self.event['id']}], 'TEST')
        with self.assertRaises(ValueError):
            self.store.state_action(other['id'], 'adopt', 'TEST', 'bad', old['id'])

    def test_human_adopted_framework_reaches_next_decision_and_writer(self):
        proposal = self.proposal()
        self.store.state_action(proposal['id'], 'adopt', 'TEST HUMAN', 'TEST decision')
        event = self.store.event({**self.body, 'as_of': now()})
        def relation(stage, value, payload):
            if stage == 'owned_decision':
                value.update(relation='consistent', state_refs=[proposal['id']])
        self.model.modify = relation
        run = self.pipeline.run(event['id'], 'en_industry')
        self.assertEqual(run['status'], 'candidates_ready')
        for stage, payload in self.model.calls:
            if stage in ('owned_decision', 'owned_candidates'):
                self.assertEqual(payload['account_state']['adopted'][0]['id'], proposal['id'])
        self.assertEqual(len(self.store.snapshot('en_industry')['adopted']), 1)

    def test_logged_client_refs_are_scoped_to_each_run(self):
        class LoggedDouble(ModelDouble):
            def __init__(self):
                super().__init__('ignore'); self.calls = []
            def __call__(self, stage, messages, max_tokens):
                response = super().__call__(stage, messages, max_tokens)
                self.calls[-1] = {'stage': stage, 'path': 'TEST-call-' + str(len(self.calls))}
                return response
        model = LoggedDouble(); pipeline = Pipeline(self.store, model)
        first = pipeline.run(self.event['id'], 'en_industry')
        second = pipeline.run(self.event['id'], 'zh_industry')
        self.assertEqual(len(first['call_refs']), 1)
        self.assertEqual(len(second['call_refs']), 1)
        self.assertNotEqual(first['call_refs'], second['call_refs'])

    def test_review_requires_all_dimensions_and_current_state(self):
        run = self.run_case(); c = run['candidates'][0]
        with self.assertRaisesRegex(ValueError, 'All editorial'):
            self.store.review(run['id'], c['id'], digest(c['text']), c['text'], 'approve', 'TEST', 'reason', {'native_language': 'pass'})
        proposal = self.proposal(); self.store.state_action(proposal['id'], 'adopt', 'TEST', 'reason')
        with self.assertRaisesRegex(ValueError, 'State/evidence'):
            self.approve(run)

    def test_edits_invalidate_machine_qa_and_require_verification_note(self):
        run = self.run_case(); c = run['candidates'][0]
        review = self.store.review(run['id'], c['id'], digest(c['text']), 'A different draft.', 'save', 'TEST', 'edit')
        self.assertFalse(review['machine_qa_applies_to_text'])
        self.assertEqual(self.store.learning_export()['rows'], [])

    def test_human_event_label_enters_future_context_not_past(self):
        run = self.run_case()
        self.store.decision_feedback(run['id'], 'ignore', 'TEST HUMAN', 'No useful audience angle')
        self.assertEqual(self.store.feedback_context('en_industry', self.event['as_of']), [])
        context = self.store.feedback_context('en_industry', now())
        self.assertEqual(context[0]['decision'], 'ignore')
        event = self.store.event({**self.body, 'as_of': now()})
        self.pipeline.run(event['id'], 'en_industry')
        payload = [p for s, p in self.model.calls if s == 'owned_decision'][-1]
        self.assertEqual(payload['human_feedback'][0]['decision'], 'ignore')
        self.assertEqual(self.store.learning_export()['rows'][0]['task'], 'event_decision')

    def test_publication_exact_text_and_engagement_do_not_adopt_beliefs(self):
        run = self.run_case(); review = self.approve(run)
        with self.assertRaisesRegex(ValueError, 'Exact'):
            self.store.publication(review['id'], 'TEST', '1', now(), 'bad')
        publication = self.store.publication(review['id'], 'TEST', '1', now(), review['text_hash'])
        self.store.engagement(publication['id'], now(), {'likes': 3}, 'TEST only')
        self.assertEqual(self.store.snapshot('en_industry')['adopted'], [])
        self.assertEqual(self.store.feedback_context('en_industry', now())[-1]['kind'], 'publication_performance')
        with self.assertRaises(ValueError):
            self.store.engagement(publication['id'], now(), {'likes': float('inf')}, 'TEST')

    def test_new_rejection_invalidates_old_publication_approval(self):
        run = self.run_case(); review = self.approve(run); c = run['candidates'][0]
        self.store.review(run['id'], c['id'], digest(c['text']), c['text'], 'reject', 'TEST', 'changed judgment')
        with self.assertRaisesRegex(ValueError, 'newer review'):
            self.store.publication(review['id'], 'TEST', '1', now(), review['text_hash'])

    def test_human_no_post_decision_blocks_approval_and_publication(self):
        run = self.run_case(); review = self.approve(run)
        self.store.decision_feedback(run['id'], 'ignore', 'TEST HUMAN', 'Do not publish this event')
        with self.assertRaisesRegex(ValueError, 'Human event decision'):
            self.approve(run)
        with self.assertRaisesRegex(ValueError, 'Human event decision'):
            self.store.publication(review['id'], 'TEST', '1', now(), review['text_hash'])
        self.store.decision_feedback(run['id'], 'speak', 'TEST HUMAN', 'Explicit reconsideration')
        self.assertTrue(self.store.human_allows_speech(run['id']))

    def test_event_revision_invalidates_old_run(self):
        run = self.run_case(); self.assertTrue(self.store.current(run))
        self.store.event({**self.body, 'as_of': '2026-01-04T00:00:00Z'})
        self.assertFalse(self.store.current(run))

    def test_followup_preserves_parent_id(self):
        run = self.run_case()
        follow = self.pipeline.run(self.event['id'], 'en_industry', run['id'])
        self.assertEqual(follow['follow_up_of'], run['id'])
        self.assertEqual(self.store.get('runs', run['id']), run)
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            self.pipeline.run(self.event['id'], 'zh_macro', run['id'])

    def test_api_readonly_views_and_persistent_human_decision(self):
        run = self.run_case()
        with patch.object(api, 'STORE', self.store):
            client = TestClient(app)
            view = client.get('/api/account-intelligence/overview')
            self.assertEqual(view.status_code, 200); self.assertEqual(len(view.json()['accounts']), 5)
            detail = client.get('/api/account-intelligence/runs/' + run['id']).json()
            self.assertEqual(detail['candidates'][0]['text_version'], digest(run['candidates'][0]['text']))
            self.assertEqual(self.store.rows('reviews'), [])
            response = client.post('/api/account-intelligence/runs/' + run['id'] + '/decision',
                json={'decision': 'ignore', 'reviewer': 'TEST', 'reason': 'No value'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(client.get('/api/account-intelligence/learning-export').json()['rows']), 1)
            self.assertEqual(client.get('/account-intelligence').status_code, 200)
            self.assertEqual(client.post('/api/account-intelligence/runs/' + run['id'] + '/decision',
                headers={'Origin': 'https://external.example'}, json={}).status_code, 403)
            self.assertEqual(client.get('/api/account-intelligence/runs/missing').status_code, 422)

    def test_event_first_api_is_retired_without_a_model_call(self):
        run = self.run_case()
        with patch.object(api, 'STORE', self.store), patch.object(api, 'Pipeline', return_value=self.pipeline):
            response = TestClient(app).post('/api/account-intelligence/events/' + self.event['id'] + '/run',
                json={'account_id': 'en_industry', 'follow_up_of': run['id'], 'current_state': True})
            self.assertEqual(response.status_code, 409)
            self.assertIn('admitted account source candidate', response.json()['detail'])


if __name__ == '__main__':
    unittest.main()
