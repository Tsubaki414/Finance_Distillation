"""P0-3b acceptance: needs_source recovery re-verifies the capture and re-ingests.

New inbox row for recovered sources (old row kept), idempotent, unrecovered
rows untouched, stale counted separately, same-language not admitted, and the
monitor item (when a monitor DB exists) reset through the revision path.
"""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from live.account_intelligence import Store
from live.account_monitor import State
from live.account_sources import ingest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('recover', ROOT / 'scripts/recover_needs_source.py')
recover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recover)

EN = 'GPU performance depends on memory bandwidth, and HBM supply sets the pace this year.'


def x_row(text=EN, pid='501', published='2026-10-03T08:00:00Z', **extra):
    return {'source_id': 'x_dylan522p', 'author_handle': 'dylan522p', 'author_name': 'Dylan Patel',
            'url': f'https://x.com/dylan522p/status/{pid}', 'original_text': text, 'source_language': 'en',
            'platform': 'x', 'source_type': 'x', 'content_complete': False,
            'completeness_basis': 'provider_body_completeness_unverified',
            'published_at': published, 'fetched_at': '2026-10-03T09:00:00Z',
            'context_items': [{'kind': 'x_capture_metadata', 'text_variants': {'text': text, 'fullText': text}}],
            **extra}


class Recover(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.as_of = '2026-10-03T12:00:00+00:00'

    def blocked(self, row):
        cand = ingest(self.store, 'zh_industry', row)['candidate']
        self.assertEqual(cand['status'], 'needs_source')
        return cand

    def test_recovered_source_gets_new_pending_row_and_old_row_kept(self):
        old = self.blocked(x_row())
        report = recover.recover(self.store, as_of=self.as_of, apply=True)
        self.assertEqual(report['recovered'], 1)
        rows = self.store.rows('inbox')
        self.assertIn(old['id'], {r['id'] for r in rows})
        new = [r for r in rows if r['id'] != old['id']]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]['status'], 'pending_selection')

    def test_idempotent(self):
        self.blocked(x_row())
        recover.recover(self.store, as_of=self.as_of, apply=True)
        n = len(self.store.rows('inbox'))
        second = recover.recover(self.store, as_of=self.as_of, apply=True)
        self.assertEqual(len(self.store.rows('inbox')), n)
        self.assertEqual(second['recovered'], 0)

    def test_dry_run_writes_nothing(self):
        self.blocked(x_row())
        n = len(self.store.rows('inbox'))
        report = recover.recover(self.store, as_of=self.as_of, apply=False)
        self.assertEqual(report['would_recover'], 1)
        self.assertEqual(len(self.store.rows('inbox')), n)

    def test_unverifiable_untouched(self):
        cut = EN[:40] + '…'
        self.blocked(x_row(text=cut, pid='502'))
        report = recover.recover(self.store, as_of=self.as_of, apply=True)
        self.assertEqual(report['recovered'], 0)
        self.assertEqual(report['still_unverified'], 1)
        self.assertEqual(len(self.store.rows('inbox')), 1)

    def test_media_gap_stays_needs_source(self):
        self.blocked(x_row(pid='503', media_dependencies=[{'kind': 'chart', 'required': True, 'url': 'u'}]))
        report = recover.recover(self.store, as_of=self.as_of, apply=True)
        self.assertEqual(report['recovered'], 0)
        self.assertEqual(report['still_blocked_other_gaps'], 1)

    def test_stale_counted_separately(self):
        self.blocked(x_row(pid='504', published='2026-09-01T08:00:00Z'))
        report = recover.recover(self.store, as_of=self.as_of, apply=True)
        self.assertEqual(report['recovered_stale'], 1)
        self.assertEqual(report['recovered'], 0)

    def test_monitor_item_reset_via_revision_path(self):
        old = self.blocked(x_row(pid='505'))
        state = State(self.store.root)
        source = self.store.get('sources', old['source_id'])
        key, _ = state.enqueue('zh_industry', 'x_dylan522p', {**source}, self.as_of, status='blocked_source')
        recover.recover(self.store, as_of=self.as_of, apply=True)
        item = {r['id']: r for r in State(self.store.root).rows('items')}[key]
        self.assertEqual(item['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
