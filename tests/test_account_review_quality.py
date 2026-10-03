"""Human-only quality metrics and exact review export; fixtures never call models."""
import copy
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import account_intelligence as api
from backend.content_dashboard import app
from live.account_intelligence import Store, digest


class ReviewQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.source = self.store.source({'id': 'test-source', 'author_name': 'Test author',
            'original_text': 'An example with a reason, a condition, and a tradeoff.',
            'source_language': 'en', 'content_complete': True, 'url': 'https://example.org/original',
            'published_at': '2026-01-01T00:00:00Z', 'fetched_at': '2026-01-01T01:00:00Z'})
        self.sequence = 0
        self.event = {'id': 'test-event', 'family': 'test-family', 'title': 'Test original',
            'mode': 'replay', 'as_of': '2026-01-01T02:00:00Z', 'source_ids': [self.source['id']]}
        handle = patch('live.account_intelligence.copy_risks', return_value=[])
        handle.start(); self.addCleanup(handle.stop)
        handle = patch.object(self.store, 'current', return_value=True)
        handle.start(); self.addCleanup(handle.stop)

    def run_record(self, text='Original draft with example.', **fields):
        self.sequence += 1
        run_id = 'test-run-' + str(self.sequence)
        run = {'id': run_id, 'pipeline': 'account_source', 'account_id': 'zh_macro',
            'batch_id': 'TEST', 'inbox_candidate_id': 'test-inbox', 'target_language': 'zh',
            'recorded_at': f'2026-01-02T00:{self.sequence:02}:00Z', 'status': 'candidates_ready',
            'event': copy.deepcopy(self.event), 'state': {'version': 'test-version'}, 'candidates': []}
        if text:
            run['candidates'] = [{'id': run_id + '-c1', 'text': text, 'machine_fidelity_pass': True,
                                  'machine_qa': {'severity': 'critical'}}]
        run.update(fields)
        return self.store.append('runs', run)

    def verdict(self, run, decision='approve', edit_class='unchanged', text=None, **extra):
        candidate = run['candidates'][0]
        return self.store.review(run['id'], candidate['id'], digest(candidate['text']),
            candidate['text'] if text is None else text, decision, 'TEST HUMAN', 'Explicit test review',
            dimensions={k: 'pass' for k in ('native_language', 'useful_examples', 'rhythm_reasoning', 'account_fit', 'angle_value')},
            risk_note='Test verification only', edit_class=edit_class, **extra)

    def test_quota_failure_does_not_consume_first_actual_draft(self):
        failed = self.run_record(None, status='execution_failed')
        first = self.run_record(follow_up_of=failed['id'])
        row = self.store.human_quality()['groups'][0]
        self.assertEqual((row['generated'], row['pending'], row['no_draft'], row['execution_failed'], row['followup_drafts']), (1, 1, 1, 1, 0))
        self.assertEqual(self.store.human_quality()['baseline_run_ids'], [first['id']])

    def test_multiple_no_draft_attempts_and_retry_of_draft_count_separately(self):
        one = self.run_record(None, status='execution_failed')
        two = self.run_record(None, status='wait', follow_up_of=one['id'])
        three = self.run_record(follow_up_of=two['id'])
        self.run_record('Improved retry.', follow_up_of=three['id'])
        row = self.store.human_quality()['groups'][0]
        self.assertEqual((row['generated'], row['no_draft'], row['followup_drafts']), (1, 2, 1))

    def test_followup_cannot_overwrite_first_rejection_or_improve_rate(self):
        first = self.run_record()
        self.verdict(first, 'reject', 'reject')
        retry = self.run_record('A better draft.', follow_up_of=first['id'])
        self.verdict(retry)
        self.verdict(first)
        row = self.store.human_quality()['groups'][0]
        self.assertEqual((row['reviewed'], row['reject'], row['unchanged'], row['followup_drafts']), (1, 1, 0, 1))
        self.assertEqual(row['ready_with_at_most_minor_rate'], 0)

    def test_changed_batch_or_inbox_does_not_hide_existing_draft_ancestry(self):
        first = self.run_record()
        self.run_record(follow_up_of=first['id'], inbox_candidate_id='recovered-inbox', batch_id='TEST2')
        rows = self.store.human_quality()['groups']
        self.assertEqual(sum(r['generated'] for r in rows), 1)
        self.assertEqual(rows[1]['followup_drafts'], 1)

    def test_machine_pass_and_saved_edits_do_not_fill_human_denominator(self):
        run = self.run_record()
        self.verdict(run, 'save', None, text='Saved text only.')
        row = self.store.human_quality()['groups'][0]
        self.assertEqual((row['machine_pass'], row['reviewed'], row['pending']), (1, 0, 1))
        self.assertIsNone(row['ready_with_at_most_minor_rate'])
        self.assertEqual(row['human_severity_counts'], {})

    def test_language_length_and_explicit_issue_severity_splits(self):
        zh = self.run_record()
        self.verdict(zh, 'reject', 'reject', error_types=['identity_transfer'], issue_annotations=[
            {'category': 'identity_transfer', 'severity': 'major', 'quote': 'Original draft', 'note': 'Test ownership problem.'}])
        en = self.run_record('A' * 1001, inbox_candidate_id='another', target_language='en')
        self.verdict(en)
        quality = self.store.human_quality()
        splits = {(r['target_language'], r['length_bucket']): r for r in quality['splits']}
        self.assertEqual(splits[('zh', 'short')]['reject'], 1)
        self.assertEqual(splits[('en', 'long')]['unchanged'], 1)
        self.assertEqual(quality['groups'][0]['error_counts'], {'identity_transfer': 1})
        self.assertEqual(quality['groups'][0]['human_severity_counts'], {'major': 1})

    def test_assisted_origin_never_fills_automated_baseline_or_rate(self):
        failed = self.run_record(None, status='execution_failed')
        assisted = self.run_record(follow_up_of=failed['id'], generation_origin='codex_assisted', generation_protocol='manual-v1')
        self.verdict(assisted)
        auto = self.run_record(follow_up_of=assisted['id'])
        quality = self.store.human_quality()
        rows = {r['generation_origin']: r for r in quality['groups']}
        self.assertEqual((rows['automated_pipeline']['generated'], rows['automated_pipeline']['pending']), (1, 1))
        self.assertIsNone(rows['automated_pipeline']['ready_with_at_most_minor_rate'])
        self.assertEqual(rows['codex_assisted']['unchanged'], 1)
        self.assertIn(auto['id'], quality['baseline_run_ids'])

    def test_human_annotations_anchor_exact_original_and_preserve_edits(self):
        run = self.run_record()
        review = self.verdict(run, edit_class='minor', text='Natural draft with example.', issue_annotations=[
            {'category': 'unnatural_language', 'severity': 'minor', 'quote': 'Original', 'note': 'Awkward word.'}])
        note = review['issue_annotations'][0]
        self.assertEqual((note['original_start'], note['original_end']), (0, 8))
        self.assertEqual(note['label_source'], 'human')
        self.assertTrue(review['edit_spans'])
        self.assertFalse(review['machine_qa_applies_to_text'])

    def test_invalid_annotation_quotes_or_severity_fail_without_record(self):
        run = self.run_record()
        for annotation in [
            {'category': 'fact', 'severity': 'invented', 'quote': '', 'note': 'Test'},
            {'category': 'fact', 'severity': 'major', 'quote': 'Not in the draft.', 'note': 'Test'},
            {'category': 'fact', 'severity': 'major', 'quote': '', 'note': ''}]:
            with self.subTest(annotation=annotation), self.assertRaises(ValueError):
                self.verdict(run, issue_annotations=[annotation])
        self.assertEqual(self.store.rows('reviews'), [])

    def test_packet_exports_exact_text_and_real_reviews_not_fake_blind_labels(self):
        run = self.run_record('Literal original <text>.', generation_origin='codex_assisted', generation_protocol='manual-v1')
        self.verdict(run, 'reject', 'reject')
        packet = self.store.review_packet('zh_macro', 'TEST')
        entry = packet['entries'][0]
        self.assertEqual(entry['sources'][0]['original_text'], self.source['original_text'])
        self.assertEqual(entry['candidates'][0]['text'], 'Literal original <text>.')
        self.assertEqual(entry['candidates'][0]['human_reviews'][0]['decision'], 'reject')
        self.assertEqual(entry['generation_origin'], 'codex_assisted')
        self.assertEqual(packet['blind_study']['status'], 'not_run')
        self.assertEqual(packet['blind_study']['human_rating_count'], 0)

    def test_source_api_passes_only_explicit_current_evidence(self):
        supplied = [{'id': 'human-check', 'source_id': self.source['id'],
                     'source_quote': 'An example', 'verification_status': 'verified',
                     'verification': {'by': 'TEST HUMAN', 'reason': 'Test only', 'method': 'manual'}}]
        with patch.object(api, 'STORE', self.store), patch.object(api, 'SourcePipeline') as pipeline:
            pipeline.return_value.run.return_value = {'id': 'test-result'}
            client = TestClient(app)
            result = client.post('/api/account-intelligence/accounts/zh_macro/inbox/test-inbox/run',
                                 json={'current_evidence': supplied})
            self.assertEqual(result.status_code, 200)
            pipeline.return_value.run.assert_called_once_with('zh_macro', 'test-inbox', None,
                                                             current_evidence=supplied)

    def test_review_packet_endpoint_scopes_account_and_batch(self):
        self.run_record()
        self.run_record('Different batch.', inbox_candidate_id='different', batch_id='OTHER')
        with patch.object(api, 'STORE', self.store):
            client = TestClient(app)
            packet = client.get('/api/account-intelligence/accounts/zh_macro/review-packet?batch_id=TEST')
            self.assertEqual(packet.status_code, 200)
            self.assertEqual(len(packet.json()['entries']), 1)
            self.assertEqual(client.get('/api/account-intelligence/accounts/en_morris_archive/review-packet').json()['entries'], [])
            self.assertEqual(client.get('/api/account-intelligence/accounts/unknown/review-packet').status_code, 422)


if __name__ == '__main__':
    unittest.main()
