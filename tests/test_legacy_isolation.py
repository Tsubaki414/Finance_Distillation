"""S0 regression: legacy_invalid_output must not reach any rendering, derivation or review route.

Read-only against data/lab.sqlite except for the routes it deliberately proves are blocked.
No model calls, no network, no generation. Run: .venv/bin/python -B tests/test_legacy_isolation.py
"""
from pathlib import Path
import sys,json,sqlite3,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'));sys.path.insert(0,str(ROOT/'scripts'))
from fastapi.testclient import TestClient
import app as backend

LEGACY_KINDS={'legacy_invalid_output','quarantined-generation'}

def legacy_ids():
    con=sqlite3.connect('file:'+str(ROOT/'data/lab.sqlite')+'?mode=ro',uri=True)
    try:
        return [r[0] for r in con.execute('SELECT id FROM records WHERE kind IN (?,?)',tuple(sorted(LEGACY_KINDS)))]
    finally:
        con.close()

class LegacyIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(backend.app)
        cls.legacy=legacy_ids()

    def test_fixture_precondition(self):
        self.assertEqual(len(self.legacy),82,'expected 45 legacy_invalid_output + 37 quarantined-generation')

    def test_render_and_derive_routes_reject_legacy_without_audit(self):
        # Every one of these reached legacy records before S0 because get() had no kind filter.
        for rid in self.legacy:
            for path in [f'/api/chart/{rid}.svg',f'/api/diagram/{rid}',f'/api/diagram-image/{rid}.svg',
                         f'/api/editorial-reviews/{rid}',f'/api/drafts/{rid}',f'/api/export/{rid}']:
                r=self.client.get(path)
                self.assertEqual(r.status_code,409,f'{path} returned {r.status_code}, expected 409')

    def test_audit_access_is_labelled_not_silent(self):
        rid=self.legacy[0]
        body=self.client.get(f'/api/drafts/{rid}?audit=true').json()
        self.assertEqual(body['content_status'],'legacy_invalid_output_not_effective_content')
        self.assertIn(body['record_kind'],LEGACY_KINDS)
        self.assertEqual(self.client.get(f'/api/chart/{rid}.svg?audit=true').status_code,200)

    def test_legacy_cannot_receive_new_edits_or_diagrams(self):
        # No audit escape hatch here: these create new records attached to invalid output.
        rid=self.legacy[0]
        self.assertEqual(self.client.post('/api/edits',json={'draft_id':rid,'text':'regression probe'}).status_code,409)
        self.assertEqual(self.client.post('/api/diagram',json={'draft_id':rid,'nodes':[{'id':'n1','label':'probe'}],'edges':[]}).status_code,409)

    def test_draft_list_never_exposes_legacy_as_content(self):
        self.assertEqual(self.client.get('/api/drafts').json(),[])
        self.assertEqual(self.client.get('/api/status').json()['drafts'],0)

    def test_blind_review_channel_is_reachable_and_excludes_legacy(self):
        body=self.client.get('/api/blind').json()
        self.assertIn('cases',body)
        texts={c['text'] for c in body['cases']}
        for rid in self.legacy:
            payload=self.client.get(f'/api/drafts/{rid}?audit=true').json()
            self.assertNotIn(payload.get('text'),texts,'legacy text surfaced in the blind set')
        # The endpoint must reject an unknown id rather than 500 — proves the channel is live.
        self.assertEqual(self.client.post('/api/blind-review',json={'case_id':'C-doesnotexist','reviewer':'regression','choice':'a','quality':3,'faithfulness':3,'edited_text':''}).status_code,422)

    def test_completed_case_assembly_matches_disk(self):
        on_disk=[c['id'] for c in backend.completed_experiment_cases()]
        for p in (ROOT/'evidence_loop/experiments/cases').glob('*.json'):
            c=json.loads(p.read_text())
            if c.get('status') in ('failed','running'):
                self.assertNotIn(c['id'],on_disk,'failed or interrupted case must never become reviewable')

class DeliveryGate(unittest.TestCase):
    """P0A-2: nothing reaches a delivery route without passing the seven gates."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(backend.app)
        cls.legacy = legacy_ids()

    def test_legacy_never_deliverable(self):
        for rid in self.legacy[:12]:
            self.assertEqual(self.client.get(f'/api/deliverable/{rid}').status_code, 409, rid)

    def test_qa_not_run_is_not_deliverable(self):
        import sys as _s
        _s.path.insert(0, str(ROOT))
        from qa.status import classify
        st = classify({'run_status': 'completed'})
        self.assertFalse(st['deliverable'])
        self.assertIn('have not been run', st['reason'])

    def test_qa_failed_is_not_deliverable(self):
        from qa.status import classify
        st = classify({'run_status': 'completed', 'qa_status': 'failed',
                       'content_status': 'blocked'})
        self.assertFalse(st['deliverable'])

    def test_passed_content_is_deliverable(self):
        from qa.status import classify
        st = classify({'run_status': 'completed', 'qa_status': 'passed',
                       'content_status': 'ready_for_pipeline'})
        self.assertTrue(st['deliverable'])

    def test_s1_case_is_blocked_by_the_gate(self):
        import json as _j
        case = _j.loads((ROOT / 'evidence_loop/experiments/cases/case-a29c6b6c0325.json').read_text())
        from qa.status import classify
        st = classify(case)
        self.assertFalse(st['deliverable'])
        self.assertEqual(st['content_status'], 'blocked')

    def test_regression_route_reports_the_replay(self):
        r = self.client.get('/api/qa/regression').json()
        self.assertEqual(r.get('caught'), 5)
        self.assertTrue(r.get('parent_case_untouched'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
