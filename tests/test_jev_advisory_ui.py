"""Saved Jev opinions are read-only and separate from acceptance and blind review."""
import copy
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from backend import account_intelligence as api
from live.account_intelligence import Store


class JevAdvisoryUITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(temporary.name)
        source = self.store.source({'id': 'jev-ui-source', 'author_name': 'Source author',
            'original_text': 'A source argument and its useful example.',
            'source_language': 'en', 'content_complete': True,
            'url': 'https://example.org/source', 'published_at': '2026-01-01T00:00:00Z',
            'fetched_at': '2026-01-01T01:00:00Z'})
        self.run = self.store.append('runs', {'id': 'jev-ui-run', 'pipeline': 'account_source',
            'account_id': 'zh_macro', 'batch_id': 'JEV-UI', 'target_language': 'zh',
            'inbox_candidate_id': 'jev-ui-inbox', 'recorded_at': '2026-01-02T00:00:00Z',
            'status': 'machine_hold', 'state': {'version': 'test'},
            'event': {'id': 'jev-ui-event', 'family': 'jev-ui-family', 'title': 'Source title',
                'mode': 'replay', 'as_of': '2026-01-01T02:00:00Z', 'source_ids': [source['id']]},
            'candidates': [{'id': 'jev-ui-draft', 'text': '原始成稿。',
                'machine_fidelity_pass': False, 'machine_qa': {'severity': 'critical'},
                'human_status': 'pending'}]})
        self.advisory = {'status': 'completed', 'advisory_only': True,
            'human_review_required': True, 'binding_verified': True,
            'body_scope': 'original_generated_draft', 'findings': [], 'checks': [],
            'feedback': {'status': 'pending_human_review', 'reviews': []}}

    def test_gets_attach_saved_advice_without_mutating_quality_or_calling_model(self):
        before = {p: p.read_bytes() for p in self.store.root.rglob('*.json')}
        quality = self.store.human_quality()
        with patch.object(api, 'STORE', self.store), patch.object(api, 'copy_risks', return_value=[]), \
                patch.object(self.store, 'current', return_value=True), \
                patch('live.jev_advisory.get_advisory', return_value=copy.deepcopy(self.advisory)) as read, \
                patch('live.jev_review_client.JevReviewClient.review') as model:
            detail = api.run_detail(self.run['id'])
            packet = api.account_review_packet('zh_macro', 'JEV-UI')
        self.assertEqual(read.call_count, 2)
        model.assert_not_called()
        for candidate in (detail['candidates'][0], packet['entries'][0]['candidates'][0]):
            self.assertEqual(candidate['jev_advisory'], self.advisory)
            self.assertEqual(candidate['text'], '原始成稿。')
            self.assertFalse(candidate['machine_fidelity_pass'])
        self.assertEqual(detail['status'], 'machine_hold')
        self.assertEqual(quality, self.store.human_quality())
        self.assertEqual(before, {p: p.read_bytes() for p in self.store.root.rglob('*.json')})

    def test_advisory_read_error_cannot_hide_candidate_or_clear_hold(self):
        with patch.object(api, 'STORE', self.store), patch.object(api, 'copy_risks', return_value=[]), \
                patch.object(self.store, 'current', return_value=True), \
                patch('live.jev_advisory.get_advisory', side_effect=ValueError('bad artifact')):
            detail = api.run_detail(self.run['id'])
        candidate = detail['candidates'][0]
        self.assertEqual(candidate['text'], '原始成稿。')
        self.assertFalse(candidate['machine_fidelity_pass'])
        self.assertFalse(candidate['jev_advisory']['binding_verified'])
        self.assertEqual(candidate['jev_advisory']['error_codes'], ['advisory_read_failed'])

    def test_no_draft_run_exposes_saved_guidance_advice_without_resuming_generation(self):
        stopped = copy.deepcopy(self.run)
        stopped.update(id='jev-ui-stopped', candidates=[], status='needs_source')
        self.store.append('runs', stopped)
        advice = {**self.advisory, 'candidate_id': None, 'findings': [{
            'dimension': 'decision_consistency', 'choice': 'flag', 'evidence': [{
                'document': 'hygiene[0]', 'span_id': 'G1', 'start': 0, 'end': 22,
                'text': 'Text is self-contained'}]}]}
        before = {p: p.read_bytes() for p in self.store.root.rglob('*.json')}
        with patch.object(api, 'STORE', self.store), patch.object(self.store, 'current', return_value=True), \
                patch('live.jev_advisory.get_advisory', return_value=advice) as read, \
                patch('live.jev_review_client.JevReviewClient.review') as model, \
                patch.object(api, 'SourcePipeline') as pipeline:
            detail = api.run_detail(stopped['id'])
        read.assert_called_once()
        self.assertIs(read.call_args.args[0], self.store)
        self.assertEqual(read.call_args.args[1]['id'], stopped['id'])
        self.assertEqual(read.call_args.kwargs, {'candidate_id': None})
        model.assert_not_called()
        pipeline.assert_not_called()
        self.assertEqual(detail['candidates'], [])
        self.assertEqual(detail['status'], 'needs_source')
        self.assertEqual(detail['jev_advisory']['findings'][0]['choice'], 'flag')
        self.assertEqual(before, {p: p.read_bytes() for p in self.store.root.rglob('*.json')})

    def test_participant_document_does_not_read_or_reveal_advisory(self):
        path = self.store.root / api.CURRENT_BLIND_DIR / 'blind' / 'zh_macro' / 'participant.md'
        path.parent.mkdir(parents=True)
        original = b'# Anonymous participant packet\n\nDraft text only.\n'
        path.write_bytes(original)
        with patch.object(api, 'REVIEW_ROOT', self.store.root), \
                patch.object(api, 'prepared_account_blind_review',
                    return_value={'participant_sha256': hashlib.sha256(original).hexdigest()}), \
                patch('live.jev_advisory.get_advisory') as read:
            response = api.account_blind_review_participant('zh_macro')
        read.assert_not_called()
        self.assertEqual(response.body, original)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for UI helper checks')
    def test_ui_folds_advice_and_preserves_original_body_scope(self):
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('frontend/account-intelligence.js','utf8').replace('guarded(()=>load());','');
const sandbox={document:{getElementById:()=>({}),addEventListener:()=>{}},window:{addEventListener:()=>{}},setInterval:()=>{}};
vm.createContext(sandbox);vm.runInContext(source,sandbox);
const c={text:'Original draft.',machine_fidelity_pass:false,deterministic_risks:[{code:'original-risk'}],jev_advisory:{
 status:'completed',binding_verified:true,body_scope:'original_generated_draft',
 findings:[{dimension:'identity_transfer',choice:'flag',confidence:.9,evidence:[{document:'draft',span_id:'D1',start:0,end:10,text:'<script>unsafe</script>'}]}],
 structural_checks:[{dimension:'account_language_fields',status:'verified',evidence:{target_language:'zh'}}],
 checks:[],feedback:{status:'pending_human_review',reviews:[]}}};
const html=sandbox.jevAdvisoryMarkup(c,'A human edited draft.');
assert(html.startsWith('<details class="jev-advisory">'));assert(!html.includes('<details open'));
assert(html.includes('只针对原始生成稿'));assert(html.includes('不改变机器保真状态'));
assert(html.includes('尚无实际人工评价'));assert(html.includes('未校准'));
assert(html.includes('&lt;script&gt;'));assert(!html.includes('<script>'));
assert(html.includes('账号语言字段'));assert(html.includes('字段一致'));assert(html.includes('target_language'));
assert(html.includes('身份转移</strong>：需人工核对'));
assert.equal(sandbox.risksFor(c).length,1);assert.equal(sandbox.risksFor(c)[0].code,'original-risk');
assert.equal(c.machine_fidelity_pass,false);assert.equal(c.text,'Original draft.');
assert(sandbox.jevAdvisoryLines(c).join('\n').includes('人工修改版不沿用这些判断'));
const stopped=sandbox.jevRunAdvisoryMarkup({jev_advisory:c.jev_advisory});
assert(stopped.startsWith('<details class="jev-advisory">'));
assert(stopped.includes('已绑定本次来源、选段与编辑决策记录；本次没有正文'));
assert(!stopped.includes('已绑定原始生成稿'));assert(!stopped.includes('尚无实际人工评价'));
assert(sandbox.jevCheckMarkup({dimension:'guidance_ownership',choice:'no_flag',evidence:{unexpected:'object'}}).includes('编辑指引中的身份归属</strong>：未标出疑点'));
c.jev_advisory.status='stale';c.jev_advisory.binding_verified=false;
const stale=sandbox.jevAdvisoryMarkup(c);
assert(!stale.includes('1 项待人工核对'));assert(!stale.includes('此次检查没有标出疑点'));
assert(stale.includes('原有检查已过期'));
assert(sandbox.jevAdvisoryLines(c).join('\n').includes('不得视为当前稿件结论'));
"""
        subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1], check=True)


if __name__ == '__main__':
    unittest.main()
