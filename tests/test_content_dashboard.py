import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend import content_dashboard as desk
from live.localization_feedback import FeedbackStore
from live.distillation_source import digest,source_record

class DashboardCases(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=FeedbackStore(Path(self.tmp.name)/'feedback')
        self.row={'run_id':'test-attempt','case':'test-case','pipeline_version':'editorial_test','prompt_version':'TEST',
          'source':source_record({'text':'The original logic matters for the result.','content_complete':True,'author_name':'Test author'}),
          'account_id':'en_industry','target_language':'en','draft_status':'draft_ready','qa_status':'model_reviewed',
          'created_at':'2026-09-30T00:00:00Z','localization':{'text':'The original logic matters for the result.'},
          'editorial_judgment':{'guidance':'TEST'},'metadata_ref':str(desk.ROOT/'runs/content_workbench_v1/test-case/metadata.json')}
        self.patches=[patch.object(desk,'STORE',self.store),patch.object(desk,'attempts',return_value=[self.row]),patch.object(desk,'source_library',return_value=[])]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.client=TestClient(desk.app)
    def test_live_data_and_human_status_are_separate(self):
        r=self.client.get('/api/content-workbench/overview');self.assertEqual(r.status_code,200)
        d=r.json();self.assertEqual(len(d['accounts']),5);self.assertEqual(d['human_review_count'],0);self.assertEqual(d['machine_ready_count'],1)
        detail=self.client.get('/api/content-workbench/attempts/test-attempt').json()
        self.assertEqual(detail['human_reviews'],[]);self.assertEqual(detail['draft'],self.row['localization']['text'])
        self.assertIn('annotations',detail)
    def test_preview_does_not_write_reviews(self):
        r=self.client.post('/api/content-workbench/attempts/test-attempt/preview',json={'text':'For my positions, the outcome matters.'})
        self.assertTrue(r.json()['requires_review']);self.assertEqual(self.store.rows('reviews'),[])
    def test_edits_persist_without_altering_source_or_publishing(self):
        before=copy.deepcopy(self.row)
        r=self.client.post('/api/content-workbench/attempts/test-attempt/review',json={'expected_version':digest(self.row['localization']['text']),
            'edited_text':'The original reasoning matters for the result.','decision':'save','reviewer':'TEST ONLY'})
        self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['changed_spans'])
        self.assertEqual(self.row,before);self.assertEqual(self.store.rows('publications'),[])
        self.assertEqual(len(self.client.get('/api/content-workbench/attempts/test-attempt').json()['human_reviews']),1)
    def test_stale_version_and_new_identity_transfer_cannot_approve(self):
        body={'expected_version':'wrong','edited_text':'Original.','decision':'approve','reviewer':'TEST ONLY'}
        self.assertEqual(self.client.post('/api/content-workbench/attempts/test-attempt/review',json=body).status_code,422)
        body.update(expected_version=digest(self.row['localization']['text']),edited_text='For my positions, the result matters.')
        self.assertEqual(self.client.post('/api/content-workbench/attempts/test-attempt/review',json=body).status_code,422)
    def test_review_is_not_reused_for_another_run_of_identical_text(self):
        candidate=self.store.register(self.row,'TEST')
        self.store.review(candidate['id'],candidate['draft_version'],candidate['original_draft'],'approve','TEST ONLY')
        self.assertEqual(desk.short(self.row)['human_status'],'approve')
        rerun={**self.row,'run_id':'another-attempt'}
        self.assertEqual(desk.short(rerun)['human_status'],'pending')
    def test_foreign_origin_and_missing_items(self):
        self.assertEqual(self.client.post('/api/content-workbench/attempts/test-attempt/preview',headers={'Origin':'https://elsewhere.invalid'},json={'text':'x'}).status_code,403)
        self.assertEqual(self.client.get('/api/content-workbench/sources/missing').status_code,404)
        self.assertEqual(self.client.get('/api/content-workbench/attempts/missing').status_code,404)
    def test_readonly_routes_never_call_a_model(self):
        with patch('live.writer_backend.complete',side_effect=AssertionError('Unexpected paid request')):
            self.assertEqual(self.client.get('/content-dashboard').status_code,200)
            self.assertEqual(self.client.get('/api/content-workbench/overview').status_code,200)
            self.assertEqual(self.client.get('/api/content-workbench/sources').status_code,200)

if __name__=='__main__':unittest.main()
