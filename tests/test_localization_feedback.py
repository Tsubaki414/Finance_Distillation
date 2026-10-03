import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from live.localization_feedback import FeedbackStore,changed_spans
from live.distillation_source import digest
from live.distillation import ContractError
from backend import localization_review as api

class FeedbackCases(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=FeedbackStore(Path(self.temp.name)/'feedback')
        self.attempt={'run_id':'test','account_id':'zh_industry','target_language':'zh','pipeline_version':'editorial_test','prompt_version':'test',
            'account_profile':{'id':'zh_industry','domain':'finance','profile_version':'TEST'},
            'domain_policy':{'id':'finance','version':'TEST'},
            'source':{'source_hash':'test','original_text':'Original source.','author_name':'Source author','url':'https://example.org/source'},
            'editorial_judgment':{'guidance':'TEST ONLY'},'draft_status':'draft_ready','localization':{'text':'数字是25，可能改善。'}}
        self.candidate=self.store.register(self.attempt,'test-attempt.json')
    def review(self,decision='approve',text='数字是25，可能改善。'):
        return self.store.review(self.candidate['id'],self.candidate['draft_version'],text,decision,'TEST HUMAN',categories=['test_only'])
    def test_append_only_edits_preserve_original_context(self):
        result=self.review(text='数字是25，或许改善。')
        self.assertEqual(result['changed_spans'][0]['before'],'可能')
        self.assertEqual(result['changed_spans'][0]['after'],'或许')
        self.assertEqual(result['source_ref'],self.attempt['source'])
        self.assertEqual(result['domain_policy'],self.attempt['domain_policy'])
        self.assertEqual(result['account_profile'],self.attempt['account_profile'])
        self.assertEqual(self.store.get('candidates',self.candidate['id'])['human_review'],'pending')
        self.review('reject');self.assertEqual(len(self.store.rows('reviews')),2)
    def test_stale_version_cannot_approve_new_content(self):
        with self.assertRaises(ContractError):self.store.review(self.candidate['id'],'old','edited','approve','TEST')
        newer={**self.attempt,'localization':{'text':'数字是50。'}}
        other=self.store.register(newer,'new.json');self.assertNotEqual(other['id'],self.candidate['id'])
        self.assertEqual(other['human_review'],'pending')
    def test_publication_and_snapshots_bind_exact_human_version(self):
        review=self.review()
        args=[review['id'],'x','123','2026-09-01T12:00:00Z',review['human_draft_version']]
        post=self.store.publication(*args)
        snap=self.store.engagement(post['id'],'2026-09-02T12:00:00Z',{'views':100},'TEST fixture screenshot')
        self.assertEqual(snap['draft_id'],review['draft_id'])
        with self.assertRaises(ContractError):self.store.publication(*args)
        self.assertFalse(self.store.summary()['writer_opinion_optimization'])
    def test_reject_mismatch_and_bad_metrics_stop(self):
        review=self.review('reject')
        with self.assertRaises(ContractError):self.store.publication(review['id'],'x','123','2026-09-01T12:00:00Z',review['human_draft_version'])
        review=self.review()
        with self.assertRaises(ContractError):self.store.publication(review['id'],'x','123','2026-09-01T12:00:00Z','wrong-hash')
        post=self.store.publication(review['id'],'x','123','2026-09-01T12:00:00Z',review['human_draft_version'])
        for metrics in [{'views':-1},{'views':float('nan')},{'likes':True}]:
            with self.assertRaises(ContractError):self.store.engagement(post['id'],'2026-09-02T00:00:00Z',metrics,'TEST')
        with self.assertRaises(ContractError):self.store.engagement(post['id'],'2026-08-01T00:00:00Z',{'views':1},'TEST')
    def test_no_human_feedback_is_never_scored(self):
        self.assertIsNone(self.store.summary()['human_edit_distance_mean'])
        self.assertEqual(self.store.summary()['human_reviews'],0)
    def test_review_api_blinds_condition_and_records_actual_submission(self):
        app=FastAPI();app.include_router(api.router)
        with patch.object(api,'STORE',self.store),TestClient(app) as client:
            rows=client.get('/api/localization-review/candidates').json()
            self.assertNotIn('pipeline_version',rows[0]);self.assertNotIn('qa',rows[0]);self.assertNotIn('editorial_judgment',rows[0])
            response=client.post('/api/localization-review/reviews',json={'candidate_id':self.candidate['id'],'expected_version':self.candidate['draft_version'],'edited_text':'数字是25，可能改善。','decision':'approve','reviewer':'TEST HUMAN'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['machine_review_after_submission']['pipeline_version'],'editorial_test')
            self.assertEqual(client.get('/api/localization-review/summary').json()['human_reviews'],1)
            self.assertEqual(client.post('/api/localization-review/register',json={'attempt_ref':'/tmp/secret.json'}).status_code,422)

if __name__=='__main__':unittest.main()
