"""Operational readiness must stay read-only and separate from content acceptance."""
import json
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from live.account_intelligence import Store
from live import pipeline_health as health


class PipelineInventoryTests(unittest.TestCase):
    def inventory(self, root, *, catalog=None, provider_error=False):
        config = {'accounts': ['one'], 'interval_seconds': 1800, 'max_drafts_per_account_day': 3}
        world = [{'account_id': 'one', 'mode': 'current', 'subscriptions': [
            {'source_id': 'writer', 'role': 'CORE', 'enabled': True},
            {'source_id': 'primary_data', 'role': 'CORE', 'enabled': True},
            {'source_id': 'watch', 'role': 'WATCHLIST', 'enabled': True}]}]
        catalog = catalog if catalog is not None else {
            'writer': {'adapter': 'x', 'handle': 'writer'},
            'primary_data': {'adapter': 'official', 'content_role': 'context_only'}}
        status = {'sources': [
            {'account': 'one', 'source': 'writer', 'cursor': '{"seen_ids":["a"]}',
             'status': 'partial_coverage', 'error': None, 'last_checked': '2026-10-02T00:00:00Z'},
            {'account': 'another', 'source': 'writer', 'cursor': '{}', 'status': 'checked'}],
            'daemon_running': True, 'budget': {'cap_usd': 100}}
        with patch.object(health, 'configuration', return_value=config), \
             patch.object(health, 'accounts', return_value=[{'id': 'one', 'enabled': True, 'language': 'zh'}]), \
             patch.object(health, 'universes', return_value=world), \
             patch.object(health, 'registry', return_value=catalog), \
             patch.object(health, 'ContentStages') as stages:
            stages.return_value.configuration = {'provider': 'test', 'model': 'test'}
            if provider_error:
                stages.side_effect = ValueError('secret value must not escape')
            return health.inventory(Store(root), status=status)

    def test_readiness_does_not_claim_quality_or_exhaustive_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'not-created'
            result = self.inventory(root)
            self.assertFalse(root.exists(), 'Observing readiness must not write a store or client directory')
        self.assertTrue(result['configuration_ready'])
        self.assertTrue(result['human_review_required'])
        self.assertFalse(result['publishing_enabled'])
        rows = result['accounts'][0]['subscriptions']
        self.assertEqual(rows[0]['status'], 'partial_coverage')
        self.assertIn('not_exhaustive', rows[0]['coverage'])
        self.assertEqual(rows[1]['purpose'], 'factual_context_only')
        self.assertEqual(rows[1]['status'], 'not_checked')
        self.assertFalse(rows[2]['polling'])

    def test_missing_adapter_is_not_treated_as_monitoring(self):
        result = self.inventory('/unused', catalog={})
        self.assertFalse(result['configuration_ready'])
        self.assertEqual(len(result['issues']), 2)
        self.assertNotIn('watch', json.dumps(result['issues']))

    def test_provider_configuration_error_never_exposes_secret(self):
        result = self.inventory('/unused', provider_error=True)
        self.assertFalse(result['configuration_ready'])
        self.assertEqual(result['provider']['error_type'], 'ValueError')
        self.assertNotIn('secret value', json.dumps(result))

    @unittest.skipUnless(shutil.which('node'), 'Node required for queue grouping check')
    def test_qa_followups_are_versions_not_additional_posts(self):
        source = (Path(__file__).resolve().parents[1] / 'frontend/account-intelligence.js').read_text()
        function = source[source.index('function reviewVersions('):source.index('function safeLink(')]
        script = '''const assert=require('assert'); const selectedAccount='one';
const draftCount=r=>r.draft_count||0;
''' + function + '''
const newest={id:'qa-resume',account_id:'one',inbox_candidate_id:'source-a',draft_count:1};
const original={id:'original',account_id:'one',inbox_candidate_id:'source-a',draft_count:1};
const different={id:'different',account_id:'one',inbox_candidate_id:'source-b',draft_count:1};
const empty={id:'failed-newest',account_id:'one',inbox_candidate_id:'source-a',draft_count:0};
const another={...original,id:'another-account',account_id:'two'};
const result=reviewVersions([empty,newest,different,original,another]);
assert.deepStrictEqual(result.latest.map(r=>r.id),['qa-resume','different','another-account']);
assert.deepStrictEqual(result.history.map(r=>r.id),['original']);
assert.equal(original.draft_count,1);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
