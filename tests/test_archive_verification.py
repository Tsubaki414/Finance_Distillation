"""P0-3c acceptance: Morris archive rows are verified with the P0-3a rule from
embedded variants or the referenced raw capture; failures say why."""
import json
from pathlib import Path
import tempfile
import unittest

from live.archive_verification import verify_archive_row
from live.monitor_intake import _load_archives

BODY = '先尝试，再观察反馈，再调整方向。重要的是反复检验，而不是等待完美计划。'


def row(**extra):
    return {'source_id': 'x_Morris_LT', 'author_handle': 'Morris_LT', 'original_text': BODY,
            'url': 'https://x.com/Morris_LT/status/77', 'content_complete': False, **extra}


class ArchiveVerification(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        raw = self.root / 'runs/disc/items.raw.json'
        raw.parent.mkdir(parents=True)
        raw.write_text(json.dumps([{'id': '1', 'text': 'other', 'fullText': 'other'},
                                   {'id': '77', 'text': BODY, 'fullText': BODY[:10] + ' https://t.co/abcDEF12'}]))

    def test_embedded_variants(self):
        r = row(context_items=[{'kind': 'x_capture_metadata', 'text_variants': {'text': BODY, 'fullText': BODY}}])
        out = verify_archive_row(r, self.root)
        self.assertTrue(out['content_complete'])
        self.assertEqual(out['archive_verification']['evidence'], 'embedded_variants')
        self.assertEqual(out['completeness_basis'], 'variants_identical')

    def test_raw_reference_relative(self):
        out = verify_archive_row(row(raw_import_ref='runs/disc/items.raw.json#/1'), self.root)
        self.assertTrue(out['content_complete'])
        self.assertEqual(out['archive_verification']['evidence'], 'raw_import')
        self.assertEqual(out['completeness_basis'], 'truncated_variant_extended')

    def test_raw_reference_moved_checkout_is_rebased(self):
        ref = '/Users/someone/Desktop/x/Finance_Distillation/runs/disc/items.raw.json#/1'
        out = verify_archive_row(row(raw_import_ref=ref), self.root)
        self.assertTrue(out['content_complete'])
        self.assertEqual(out['archive_verification']['raw_ref_resolved'], 'runs/disc/items.raw.json')

    def test_raw_item_found_by_post_id_when_index_moved(self):
        out = verify_archive_row(row(raw_import_ref='runs/disc/items.raw.json#/0'), self.root)
        self.assertTrue(out['content_complete'])

    def test_missing_file_stays_unverified_with_reason(self):
        out = verify_archive_row(row(raw_import_ref='runs/none.json#/0'), self.root)
        self.assertFalse(out['content_complete'])
        self.assertEqual(out['archive_verification']['reason'], 'raw_ref_unresolvable')

    def test_stored_body_must_equal_verified_body(self):
        r = row(original_text=BODY[:12],
                context_items=[{'kind': 'x_capture_metadata', 'text_variants': {'text': BODY, 'fullText': BODY}}])
        out = verify_archive_row(r, self.root)
        self.assertFalse(out['content_complete'])
        self.assertEqual(out['archive_verification']['reason'], 'stored_body_differs_from_capture')

    def test_ellipsis_body_unverified(self):
        cut = BODY[:12] + '…'
        r = row(original_text=cut,
                context_items=[{'kind': 'x_capture_metadata', 'text_variants': {'text': cut, 'fullText': cut}}])
        out = verify_archive_row(r, self.root)
        self.assertFalse(out['content_complete'])
        self.assertEqual(out['archive_verification']['reason'], 'ellipsis_tail')

    def test_no_evidence(self):
        out = verify_archive_row(row(), self.root)
        self.assertFalse(out['content_complete'])
        self.assertEqual(out['archive_verification']['reason'], 'no_capture_evidence')

    def test_complete_rows_untouched(self):
        r = row(content_complete=True)
        self.assertEqual(verify_archive_row(r, self.root), r)

    def test_load_archives_applies_verification(self):
        archive = self.root / 'a.json'
        archive.write_text(json.dumps([row(context_items=[{'kind': 'x_capture_metadata',
                                                           'text_variants': {'text': BODY, 'fullText': BODY}}])]))
        rows, _ = _load_archives([archive])
        self.assertTrue(rows[0]['content_complete'])


if __name__ == '__main__':
    unittest.main()
