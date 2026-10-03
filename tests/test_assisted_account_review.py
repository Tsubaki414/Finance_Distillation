import copy
import json
import unittest
import tempfile
from pathlib import Path
from scripts.review_assisted_account_sources import prepare, translation_record, PACKET, OUTPUT


class AssistedReviewTests(unittest.TestCase):
    def setUp(self):
        self.cases = json.loads(PACKET.read_text())['cases']
        self.submissions = json.loads((OUTPUT / 'edit_submissions.json').read_text())['cases']

    def test_real_edits_and_translation_provenance_are_exact(self):
        for case, submission in zip(self.cases, self.submissions):
            _, rows, ledger = prepare(case, submission)
            translation_record(case)
            self.assertEqual([r['paragraph_id'] for r in rows],
                             [r['paragraph_id'] for r in case['translation']['segments']])
            self.assertEqual(len(ledger), len(submission['edits']))
            self.assertEqual(submission['generation_origin'], 'codex_assisted')

    def test_stale_input_versions_and_wrong_parent_fail(self):
        for key in ('source_hash', 'translation_id', 'selection_id', 'follow_up_of', 'account_id'):
            item = copy.deepcopy(self.submissions[0]); item[key] = 'wrong'
            with self.assertRaises(ValueError): prepare(self.cases[0], item)

    def test_unadmitted_source_never_gets_assisted_draft(self):
        with self.assertRaises(ValueError): prepare(self.cases[3], self.submissions[0])

    def test_assisted_edits_cannot_pose_as_original_model_or_add_background(self):
        for patch in ({'generation_origin': 'automated_pipeline'}, {'added_background': ['new fact']}):
            with self.assertRaises(ValueError): prepare(self.cases[0], {**self.submissions[0], **patch})

    def test_zero_edit_morris_stays_verbatim_but_is_explicitly_assessed(self):
        value, rows, ledger = prepare(self.cases[2], self.submissions[2])
        self.assertEqual(rows, self.cases[2]['translation']['segments'])
        self.assertEqual(ledger, [])
        self.assertEqual(value, {'edits': [], 'added_background': []})

    def test_packet_export_cannot_overwrite_a_saved_evaluation(self):
        from scripts.run_account_sources import packet
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'original-review'
            target.mkdir()
            saved = target / 'exact_outputs.json'
            saved.write_text('original evaluation')
            with self.assertRaises(FileExistsError): packet(None, target)
            self.assertEqual(saved.read_text(), 'original evaluation')


if __name__ == '__main__': unittest.main()
