"""Saved supplemental diagnostics must bind to this exact assisted draft and source."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from backend import account_intelligence as api
from live.account_intelligence import Store, digest


class SupplementalReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'store')
        handle = patch.object(api, 'REVIEW_ROOT', self.root)
        handle.start(); self.addCleanup(handle.stop)
        self.source = self.store.source({'id': 'test-source', 'original_text': 'An example, reason and tradeoff.',
            'source_language': 'en', 'url': 'https://example.org/original',
            'published_at': '2026-01-01T00:00:00Z', 'fetched_at': '2026-01-01T01:00:00Z'})
        self.adaptation = {'id': 'test-run-adaptation', 'account_id': 'zh_macro',
            'generation_origin': 'codex_assisted', 'source': copy.deepcopy(self.source),
            'final_draft': '例子、理由与取舍。', 'selection': {'passages': []}, 'translation': {'text': '例子、理由与取舍。'}}
        self.run = {'id': 'test-run', 'pipeline': 'account_source', 'account_id': 'zh_macro',
            'batch_id': 'TEST', 'inbox_candidate_id': 'test-inbox', 'fixture_id': 'F02',
            'recorded_at': '2026-01-02T00:00:00Z', 'status': 'machine_hold', 'target_language': 'zh',
            'generation_origin': 'codex_assisted', 'source_adaptation': copy.deepcopy(self.adaptation),
            'event': {'id': 'test-event', 'family': 'test-family', 'title': 'Test', 'mode': 'replay',
                      'as_of': '2026-01-02T00:00:00Z', 'source_ids': [self.source['id']]},
            'candidates': [{'id': 'test-run-c1', 'text': self.adaptation['final_draft'],
                            'machine_fidelity_pass': False, 'human_status': 'pending',
                            'deterministic_risks': [{'code': 'original-hold'}]}]}
        self.candidate = self.run['candidates'][0]
        self.input_path = 'runs/account_sources_v1/assisted_followups/F02/result.json'
        self.qa_path = 'runs/account_sources_v1/assisted_followups/F02/supplemental_qa/result.json'
        self.report_path = 'runs/account_sources_v1/completion_v2/validator_recheck.json'
        self.write(self.input_path, self.adaptation)
        self.qa = {'fixture_id': 'F02', 'parent_adaptation_id': self.adaptation['id'],
            'candidate_hash': digest(self.candidate['text']), 'generation_origin': 'codex_assisted',
            'status': 'model_reviewed', 'deterministic_hold_preserved': True,
            'semantic': {'checks': [], 'findings': [{'status': 'open', 'code': 'unnecessary-edit'}]},
            'model_responses': [{'finish_reason': 'stop', 'refusal': None, 'model': 'test-model'}]}
        self.write(self.qa_path, self.qa)
        hashes = []
        for name in sorted(api.VALIDATOR_FILES):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('test validator ' + name)
            hashes.append({'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        self.report = {'checked_at': '2026-01-03T00:00:00Z', 'versions': {'numeric': 'test-v2'},
            'code_hashes': hashes, 'cases': [{'fixture': 'F02', 'input_path': self.input_path,
                'input_sha256': hashlib.sha256((self.root / self.input_path).read_bytes()).hexdigest(),
                'draft_sha256': digest(self.candidate['text']), 'machine_acceptance_changed': False,
                'prior_deterministic_findings': 6, 'new_findings': []}]}
        self.write(self.report_path, self.report)

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False))

    def evidence(self, run=None, candidate=None):
        return api.supplemental_review(self.store, run or self.run, candidate or self.candidate)

    def test_valid_evidence_does_not_clear_original_hold_or_create_human_labels(self):
        before = copy.deepcopy(self.run)
        result = self.evidence()
        self.assertTrue(result['binding_verified'])
        self.assertEqual(result['status_effect'], 'diagnostic_only')
        self.assertEqual(result['semantic']['semantic']['findings'][0]['code'], 'unnecessary-edit')
        self.assertEqual(result['validator_recheck']['new_findings'], [])
        self.assertNotIn('human_status', result)
        self.assertEqual(self.run, before)

    def test_wrong_candidate_identity_or_text_cannot_borrow_diagnostics(self):
        for changes in ({'id': 'another-candidate'}, {'text': self.candidate['text'] + '新增。'}):
            with self.subTest(changes=changes):
                self.assertIsNone(self.evidence(candidate={**self.candidate, **changes}))

    def test_wrong_parent_or_candidate_hash_rejects_semantic_result(self):
        for field in ('parent_adaptation_id', 'candidate_hash', 'fixture_id'):
            with self.subTest(field=field):
                self.write(self.qa_path, {**self.qa, field: 'wrong'})
                result = self.evidence()
                self.assertNotIn('semantic', result)
                self.assertIn('validator_recheck', result)

    def test_changed_adaptation_or_original_source_cannot_borrow_evidence(self):
        run = copy.deepcopy(self.run)
        run['source_adaptation']['source']['original_text'] += ' Changed.'
        self.assertIsNone(self.evidence(run=run))
        changed = {**self.source, 'original_text': self.source['original_text'] + ' Changed.'}
        # Even a stale recorded source_hash may not conceal changed source text.
        with patch.object(self.store, 'get', return_value=changed):
            self.assertIsNone(self.evidence())
        for field, value in (('published_at', '2026-09-01T00:00:00Z'), ('author_name', 'Other author')):
            with patch.object(self.store, 'get', return_value={**self.source, field: value}):
                self.assertIsNone(self.evidence())

    def test_incomplete_or_refused_semantic_attempt_is_not_a_completed_diagnostic(self):
        for changes in ({'status': 'execution_failed'},
                        {'model_responses': [{'finish_reason': 'length'}]},
                        {'model_responses': [{'finish_reason': 'stop', 'refusal': 'refused'}]},
                        {'model_responses': []}):
            with self.subTest(changes=changes):
                self.write(self.qa_path, {**self.qa, **changes})
                self.assertNotIn('semantic', self.evidence())

    def test_validator_requires_exact_code_input_and_draft_hashes(self):
        for field in ('input_sha256', 'draft_sha256', 'input_path'):
            with self.subTest(field=field):
                report = copy.deepcopy(self.report)
                report['cases'][0][field] = 'wrong'
                self.write(self.report_path, report)
                self.assertNotIn('validator_recheck', self.evidence())
        self.write(self.report_path, self.report)
        path = self.root / 'live/numeric_fidelity.py'
        path.write_text('new validator code')
        self.assertNotIn('validator_recheck', self.evidence())
        self.assertIn('semantic', self.evidence())

    def test_report_paths_and_fixture_are_allowlisted_not_caller_paths(self):
        for fixture in ('F03', '../F02', 'F02/supplemental_qa'):
            self.assertIsNone(self.evidence(run={**self.run, 'fixture_id': fixture}))
        report = copy.deepcopy(self.report)
        report['code_hashes'][0]['path'] = '../../outside'
        self.write(self.report_path, report)
        self.assertNotIn('validator_recheck', self.evidence())
        self.assertIsNone(self.evidence(run={**self.run, 'generation_origin': 'automated_pipeline'}))

    def test_api_and_packet_are_read_only_and_do_not_inflate_quality(self):
        self.store.append('runs', self.run)
        quality = self.store.human_quality()
        files = {str(p): p.read_bytes() for p in self.store.root.rglob('*.json')}
        with patch.object(api, 'STORE', self.store), patch.object(api, 'copy_risks', return_value=[]), \
                patch.object(self.store, 'current', return_value=True):
            detail = api.run_detail(self.run['id'])
            packet = api.account_review_packet('zh_macro', 'TEST')
        for candidate in (detail['candidates'][0], packet['entries'][0]['candidates'][0]):
            self.assertIn('supplemental_review', candidate)
            self.assertFalse(candidate['machine_fidelity_pass'])
            self.assertEqual(candidate['human_status'], 'pending')
        self.assertEqual(detail['status'], 'machine_hold')
        self.assertEqual(self.store.human_quality(), quality)
        self.assertEqual({str(p): p.read_bytes() for p in self.store.root.rglob('*.json')}, files)

    def prepare_blind_packet(self):
        participant = self.root / api.BLIND_REVIEW_DIR / 'PARTICIPANT.md'
        participant.parent.mkdir(parents=True, exist_ok=True)
        participant.write_text('Anonymous review material; no answer key.\n')
        inputs = []
        for name in sorted(api.BLIND_INPUTS):
            path = self.root / name
            if not path.exists():
                self.write(name, {'test': True})
            inputs.append({'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        manifest = {'status': 'prepared_not_administered', 'human_ratings_count': 0,
            'participant_file': 'PARTICIPANT.md', 'participant_sha256': hashlib.sha256(participant.read_bytes()).hexdigest(),
            'item_count': 4, 'system_candidates': 2, 'collected_public_posts': 2, 'input_files': inputs,
            'limitations': ['Public attribution is not proof of human-only authorship'],
            'human_work_remaining': ['Actual curator confirmation', 'Actual reviewer ratings']}
        self.write(api.BLIND_REVIEW_DIR + '/MANIFEST.json', manifest)
        return participant, manifest

    def test_legacy_prepared_packet_cannot_replace_current_account_packet(self):
        participant, _ = self.prepare_blind_packet()
        self.store.append('runs', self.run)
        with patch.object(api, 'STORE', self.store):
            packet = api.account_review_packet('zh_macro', 'TEST')
        study = packet['blind_study']
        self.assertEqual(study['status'], 'not_run')
        self.assertNotIn('prepared_packet', study)
        self.assertEqual(study['human_rating_count'], 0)
        self.assertFalse(study['registered_in_store'])
        self.assertIn('Registered human-validated', study['real_reference_count_basis'])
        legacy = api.prepared_blind_review()
        self.assertEqual(legacy['status'], 'prepared_not_administered')
        self.assertEqual(legacy['item_count'], 4)
        self.assertEqual(legacy['human_ratings_count'], 0)
        self.assertNotIn('answer_key_file', legacy)
        self.assertEqual(legacy['human_work_remaining'], ['Actual curator confirmation', 'Actual reviewer ratings'])
        self.assertEqual(api.blind_review_participant().body, participant.read_bytes())

    def test_changed_blind_packet_or_input_cannot_be_served_as_bound_packet(self):
        participant, manifest = self.prepare_blind_packet()
        participant.write_text('Modified after preparation')
        self.assertIsNone(api.prepared_blind_review())
        with self.assertRaises(api.HTTPException):
            api.blind_review_participant()
        self.prepare_blind_packet()
        (self.root / 'data/raw_posts.jsonl').write_text('changed source corpus')
        self.assertIsNone(api.prepared_blind_review())
        self.prepare_blind_packet()
        manifest['input_files'][0]['path'] = '../external'
        self.write(api.BLIND_REVIEW_DIR + '/MANIFEST.json', manifest)
        self.assertIsNone(api.prepared_blind_review())

    @unittest.skipUnless(shutil.which('node'), 'Node is needed for UI helper checks')
    def test_ui_prioritizes_open_semantic_issue_and_preserves_original_checks(self):
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const script=fs.readFileSync('frontend/account-intelligence.js','utf8').replace('guarded(()=>load());','');
const sandbox={document:{getElementById:()=>({}),addEventListener:()=>{}},window:{addEventListener:()=>{}},setInterval:()=>{}};
vm.createContext(sandbox);vm.runInContext(script,sandbox);
const c={machine_fidelity_pass:false,deterministic_risks:[{code:'oldfalsepositive'}],
 supplemental_review:{binding_verified:true,semantic:{semantic:{findings:[
 {status:'metadata_note',code:'metadata-only'},
 {status:'open',code:'unnecessary-edit',output_quote:'<script>alert(1)</script>'}]}},
 validator_recheck:{new_findings:[],prior_deterministic_findings:6}}};
assert.equal(sandbox.risksFor(c)[0].code,'unnecessary-edit');
assert.equal(sandbox.risksFor(c).length,1);
const markup=sandbox.riskMarkup(c);
assert(markup.indexOf('unnecessary-edit')<markup.indexOf('oldfalsepositive'));
assert(markup.includes('原始机器 hold 保留'));
assert(markup.includes('&lt;script&gt;'));assert(!markup.includes('<script>'));
assert(!markup.includes('risk-clear'));
assert(sandbox.reviewEvidenceLines(c).join('\n').includes('oldfalsepositive'));
assert(sandbox.reviewEvidenceLines(c).join('\n').includes('metadata-only'));
sandbox.preparation={binding_verified:true,item_count:4,system_candidates:2,collected_public_posts:2};
vm.runInContext('data={blind_review_preparation:preparation}',sandbox);
const blind=sandbox.blindStudyMarkup();assert(blind.includes('历史辅助编辑盲测 · 4 条'));
assert(blind.includes('不属于本账号的 5 + 5 自动稿盲测'));
assert(!blind.includes('KEY.json'));
sandbox.currentPreparation={binding_verified:true,item_count:10,system_candidates:5,collected_public_posts:5,participant_url:'/participant'};
vm.runInContext("data.account_blind_review_preparations={[selectedAccount]:currentPreparation}",sandbox);
const current=sandbox.blindStudyMarkup();assert(current.includes('本批 10 条已混排'));
assert(current.includes('尚无真人评分'));assert(current.includes('是否使用 AI 未知'));
assert(!current.includes('KEY.json'));
"""
        subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1], check=True)


if __name__ == '__main__':
    unittest.main()
