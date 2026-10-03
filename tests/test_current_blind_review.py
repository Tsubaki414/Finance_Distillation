"""Current account blind packets: exact binding, isolated download, no labels written."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend import account_intelligence as api
from backend.content_dashboard import app


class CurrentBlindReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.account = 'en_morris_archive'
        self.packet_path = self.root / api.CURRENT_BLIND_DIR / 'packet.json'
        original = json.loads((api.REVIEW_ROOT / api.CURRENT_BLIND_DIR / 'packet.json').read_text())
        for relative in original['input_sha256']:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(api.REVIEW_ROOT / relative, destination)
        for account in original['accounts']:
            for draft in account['drafts']:
                relative = Path(draft['adaptation_artifact']).relative_to(api.REVIEW_ROOT)
                draft['adaptation_artifact'] = str(self.root / relative)
        self.packet_path.parent.mkdir(parents=True, exist_ok=True)
        self.packet_path.write_text(json.dumps(original, ensure_ascii=False))
        shutil.copytree(api.REVIEW_ROOT / api.CURRENT_BLIND_DIR / 'blind', self.packet_path.parent / 'blind')
        self.directory = self.packet_path.parent / 'blind' / self.account
        handle = patch.object(api, 'REVIEW_ROOT', self.root)
        handle.start();self.addCleanup(handle.stop)
        self.client = TestClient(app)

    def test_three_current_downloads_match_exact_files_and_expose_no_answer_metadata(self):
        with patch.object(api.STORE, 'append', side_effect=AssertionError('No record writes')):
            for account in api.CURRENT_BLIND_ACCOUNTS:
                metadata = api.prepared_account_blind_review(account)
                self.assertTrue(metadata['binding_verified'])
                self.assertEqual((metadata['system_candidates'],metadata['collected_public_posts']), (5,5))
                self.assertEqual(metadata['human_ratings_count'],0)
                response = self.client.get(metadata['participant_url'])
                self.assertEqual(response.status_code,200,response.text)
                expected = (self.packet_path.parent / 'blind' / account / 'participant.md').read_bytes()
                self.assertEqual(response.content,expected)
                for forbidden in ('PRIVATE_ANSWER_KEY','run_id','machine_status','matched_selection_id','body_sha256'):
                    self.assertNotIn(forbidden,response.text)
                    self.assertNotIn(forbidden,json.dumps(metadata))

    def test_changed_participant_body_is_rejected(self):
        path = self.directory / 'participant.json'
        value = json.loads(path.read_text());value['items'][0]['text']+=' added words'
        path.write_text(json.dumps(value))
        self.assertIsNone(api.prepared_account_blind_review(self.account))

    def test_extra_private_fields_or_answer_appendix_cannot_be_served(self):
        path = self.directory / 'participant.json'
        original = path.read_text();value = json.loads(original)
        value['items'][0]['run_id']='private-identity'
        path.write_text(json.dumps(value))
        self.assertIsNone(api.prepared_account_blind_review(self.account))
        path.write_text(original)
        with (self.directory / 'participant.md').open('a') as stream:
            stream.write('\nPRIVATE_ANSWER_KEY: not participant material')
        response = self.client.get(f'/api/account-intelligence/accounts/{self.account}/blind-review/participant')
        self.assertEqual(response.status_code,409)
        self.assertNotIn('PRIVATE_ANSWER_KEY',response.text)

    def test_source_or_adaptation_hash_change_rejects_packet(self):
        packet = json.loads(self.packet_path.read_text())
        path = Path(packet['accounts'][0]['drafts'][0]['adaptation_artifact'])
        value = json.loads(path.read_text());value['source']['original_text']+=' changed source'
        path.write_text(json.dumps(value))
        self.assertIsNone(api.prepared_account_blind_review(self.account))

    def test_current_store_body_must_match_frozen_packet(self):
        real_get = api.STORE.get
        def changed_source(kind,key):
            value = copy.deepcopy(real_get(kind,key))
            if kind == 'sources':
                value['original_text']+=' changed stored source'
            return value
        with patch.object(api.STORE,'get',side_effect=changed_source):
            self.assertIsNone(api.prepared_account_blind_review(self.account))

    def test_later_batch_attempt_summary_does_not_replace_locked_cohort(self):
        path = self.root / 'runs/content_batch_v2/outcomes/zh_industry/summary.json'
        path.write_text('{"new_follow_up":"does not alter the frozen fifteen texts"}')
        self.assertTrue(api.prepared_account_blind_review(self.account)['binding_verified'])

    def test_unknown_account_does_not_fallback_to_assisted_packet(self):
        response = self.client.get('/api/account-intelligence/accounts/en_macro/blind-review/participant')
        self.assertEqual(response.status_code,409)

    @unittest.skipUnless(shutil.which('node'),'Node required for view contract check')
    def test_current_account_switch_changes_packet_link_and_labels_legacy_separately(self):
        source = (Path(__file__).resolve().parents[1] / 'frontend/account-intelligence.js').read_text()
        function = source[source.index('function blindStudyMarkup(){'):source.index('function blindStudyLines(study)')]
        harness = """
const assert=require('assert');let selectedAccount='zh_macro';
const esc=String,json=JSON.stringify;
const data={account_blind_review_preparations:{zh_macro:{binding_verified:true,item_count:10,participant_url:'/macro'},zh_industry:{binding_verified:true,item_count:10,participant_url:'/industry'}},blind_review_preparation:{binding_verified:true,item_count:4,participant_url:'/old-assisted'}};
"""+function+"""
assert(blindStudyMarkup().includes('href="/macro"'));
assert(blindStudyMarkup().includes('历史辅助编辑盲测'));
selectedAccount='zh_industry';assert(blindStudyMarkup().includes('href="/industry"'));
assert(!blindStudyMarkup().includes('href="/macro"'));
selectedAccount='en_morris_archive';assert(blindStudyMarkup().includes('准备包暂不可用'));
"""
        result = subprocess.run(['node','-e',harness],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__':
    unittest.main()
