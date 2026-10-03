"""Integrity and disclosure boundaries of the offline content review export."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_content_batch_packet import (
    ACCOUNTS, attach_agent_observations, baseline_info, bind_draft, blind_packet, build, digest,
    match_references, reference_text, render_review, write_packet,
)


class ContentBatchPacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "batch"
        self.refs = []
        for index in range(6):
            text = f"A distinct public risk and wealth observation {index}."
            self.refs.append({"reference_id": f"R{index}", "text": text,
                              "text_sha256": digest(text), "language": "en",
                              "author_handle": "PRIVATE_AUTHOR", "url": "https://example.com/post",
                              "context_items": [{"kind": "reply_parent", "text": "PRIVATE_PARENT"}]})

    def fixture(self, index=0, account="en_morris_archive", machine_pass=True):
        source = "原文观点。\n\n必要的条件与例子。"
        text = f"Exact draft {index}: risk and wealth.\n\nSecond paragraph. `literal`"
        outcome = {"selection_id": f"D{index}", "account_id": account, "run_id": f"run-{account}-{index}",
                   "generation_origin": "automated_pipeline", "source_hash": digest(source),
                   "final_draft": text, "status": "candidates_ready" if machine_pass else "machine_hold",
                   "machine_pass": machine_pass, "why": "PRIVATE_QA_REASON"}
        curated = {"selection_id": f"D{index}", "source": {"original_text": source}, "topic": "risk and wealth"}
        adaptation = {"source": {"original_text": source, "author_name": "PRIVATE_SOURCE_AUTHOR", "content_kind": "verified_complete_excerpt"},
                      "final_draft": text, "selection": {"passages": [{"paragraph_id": "P1", "start": 0,
                            "end": len(source), "exact_text": source}]},
                      "machine_fidelity": {"status": "pass" if machine_pass else "hold",
                                           "qa": {"findings": [] if machine_pass else [{"code": "numeric_drift", "detail": "PRIVATE_QA"}]}},
                      "risks": []}
        path = self.root / f"{account}-{index}.json"
        path.write_text(json.dumps(adaptation))
        outcome["adaptation_path"] = str(path)
        return outcome, curated, adaptation, path

    def bound(self, index=0, machine_pass=True):
        o, c, a, p = self.fixture(index, machine_pass=machine_pass)
        return bind_draft(o, c, a, "en", baseline_info({"verified_length_stats": {"min": 3, "p90": 5}}, "en"), p)

    def prepare_tree(self, count=5):
        for account in ACCOUNTS:
            folder = self.base / "source_selection" / account
            folder.mkdir(parents=True)
            outcomes = self.base / "outcomes" / account
            outcomes.mkdir(parents=True)
            sources, items = [], []
            for index in range(count):
                o, c, _, _ = self.fixture(index, account, machine_pass=index != 1)
                sources.append(c)
                items.append(o)
            refs = copy.deepcopy(self.refs)
            for r in refs:
                r["language"] = "en" if account == "en_morris_archive" else "zh"
            for name, value in [("selected_sources.json", {"sources": sources}),
                                ("references.json", {"references": refs}),
                                ("length_baseline.json", {"verified_length_stats": {"min": 3, "p90": 5},
                                                          "unicode_character_summary": {"min": 3, "p90": 5}})]:
                (folder / name).write_text(json.dumps(value))
            (outcomes / "summary.json").write_text(json.dumps({"items": items}))

    def test_exact_draft_whitespace_source_and_hold_survive(self):
        draft = self.bound(machine_pass=False)
        self.assertEqual(draft["final_draft"], "Exact draft 0: risk and wealth.\n\nSecond paragraph. `literal`")
        self.assertEqual(draft["machine"]["outcome_status"], "machine_hold")
        self.assertFalse(draft["machine"]["pass"])
        self.assertEqual(draft["risks"][0]["code"], "numeric_drift")
        self.assertIsNone(draft["human_review"]["edit_class"])
        self.assertEqual(draft["source"]["original_text"], "原文观点。\n\n必要的条件与例子。")

    def test_tampered_adaptation_draft_is_rejected(self):
        o, c, a, p = self.fixture()
        a["final_draft"] += " changed"
        with self.assertRaisesRegex(ValueError, "differs from adaptation"):
            bind_draft(o, c, a, "en", baseline_info({}, "en"), p)

    def test_wrong_source_hash_is_rejected(self):
        o, c, a, p = self.fixture()
        o["source_hash"] = digest("another source")
        with self.assertRaisesRegex(ValueError, "Source body/hash mismatch"):
            bind_draft(o, c, a, "en", baseline_info({}, "en"), p)

    def test_invalid_selected_range_is_rejected(self):
        o, c, a, p = self.fixture()
        a["selection"]["passages"][0]["start"] = 1
        with self.assertRaisesRegex(ValueError, "range mismatch"):
            bind_draft(o, c, a, "en", baseline_info({}, "en"), p)

    def test_assisted_origin_cannot_enter_automatic_cohort(self):
        o, c, a, p = self.fixture()
        o["generation_origin"] = "codex_assisted"
        with self.assertRaisesRegex(ValueError, "Non-automatic"):
            bind_draft(o, c, a, "en", baseline_info({}, "en"), p)

    def test_adaptation_origin_account_and_language_cannot_be_mislabeled(self):
        for field, value in [("generation_origin", "codex_assisted"), ("account_id", "zh_industry"), ("target_language", "zh")]:
            with self.subTest(field=field):
                o, c, a, p = self.fixture()
                a[field] = value
                with self.assertRaises(ValueError):
                    bind_draft(o, c, a, "en", baseline_info({}, "en"), p)

    def test_reference_hash_and_duplicate_body_fail_closed(self):
        bad = {**self.refs[0], "text": "rewritten public post"}
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            reference_text(bad)
        with self.assertRaisesRegex(ValueError, "Duplicate reference"):
            match_references([self.bound()], [self.refs[0], self.refs[0]], "en")

    def test_blind_items_exact_5_plus_5_no_source_qa_answer_metadata(self):
        drafts = [self.bound(i, i != 1) for i in range(5)]
        participant, key = blind_packet("en_morris_archive", drafts, self.refs, "en")
        self.assertEqual(len(participant["items"]), 10)
        self.assertEqual(sum(x["kind"] == "automatic_draft" for x in key["items"]), 5)
        self.assertEqual(sum(x["kind"] == "public_reference" for x in key["items"]), 5)
        blob = json.dumps(participant)
        for forbidden in ("PRIVATE_SOURCE_AUTHOR", "PRIVATE_AUTHOR", "PRIVATE_PARENT", "PRIVATE_QA", "machine_hold", "automatic_draft", "public_reference"):
            self.assertNotIn(forbidden, blob)
        for item in participant["items"]:
            self.assertEqual(set(item), {"opaque_id", "text", "response"})
            self.assertTrue(all(value is None for value in item["response"].values()))
        texts = {x["text"] for x in participant["items"]}
        self.assertTrue(all(d["final_draft"] in texts for d in drafts))

    def test_blind_order_deterministic_and_context_private(self):
        drafts = [self.bound()]
        first = blind_packet("en_morris_archive", drafts, self.refs, "en")
        self.assertEqual(first, blind_packet("en_morris_archive", drafts, self.refs, "en"))
        private_ref = next(x for x in first[1]["items"] if x["kind"] == "public_reference")
        self.assertEqual(private_ref["reference"]["context_items"][0]["text"], "PRIVATE_PARENT")
        self.assertTrue(first[1]["public_reference_does_not_prove_human_only_authorship"])

    def test_cross_language_reference_is_not_selected(self):
        refs = [{**r, "language": "zh"} for r in self.refs]
        with self.assertRaisesRegex(ValueError, "same-language"):
            match_references([self.bound()], refs, "en")

    def test_agent_note_requires_exact_run_draft_and_source_binding(self):
        draft = self.bound()
        valid = {"selection_id": draft["selection_id"], "run_id": draft["run_id"],
                 "draft_sha256": draft["draft_sha256"], "source_hash": draft["source"]["source_hash"],
                 "detail": "Inspected source boundary; agent opinion, not a human rating"}
        wrong_draft = {**valid, "draft_sha256": digest("stale")}
        wrong_source = {**valid, "source_hash": digest("wrong")}
        wrong_run = {**valid, "run_id": "another-run"}
        attach_agent_observations(draft, [wrong_draft, valid, wrong_source, wrong_run])
        self.assertEqual(draft["agent_observations"], [valid])
        self.assertIsNone(draft["human_review"]["edit_class"])

    def test_complete_packet_and_rerun_preserve_separate_human_results(self):
        self.prepare_tree()
        packet = build(self.base, self.root)
        self.assertEqual(packet["draft_count"], 15)
        self.assertEqual(packet["human_reviews"], 0)
        output = self.base / "review"
        write_packet(packet, output)
        response = output / "human_results.json"
        response.write_text('{"actual_human_work":"do not overwrite"}')
        write_packet(build(self.base, self.root), output)
        self.assertEqual(response.read_text(), '{"actual_human_work":"do not overwrite"}')
        exported = read_json(output / "packet.json")
        self.assertFalse(exported["publishing_enabled"])
        self.assertNotIn("blind_private_key", exported["accounts"][0])
        md = (output / "REVIEW_PACKET.md").read_text()
        self.assertIn("**machine_hold**", md)
        self.assertIn(packet["accounts"][0]["drafts"][0]["final_draft"], md)

    def test_missing_drafts_are_never_padded_or_called_complete(self):
        self.prepare_tree(count=4)
        with self.assertRaisesRegex(ValueError, "Incomplete packet"):
            build(self.base, self.root)
        partial = build(self.base, self.root, allow_partial=True)
        self.assertEqual(partial["draft_count"], 12)
        self.assertEqual(partial["status"], "partial_pending_generation")
        self.assertEqual(len(partial["gaps"]), 3)

    def test_duplicate_summary_identity_is_rejected(self):
        self.prepare_tree()
        path = self.base / "outcomes/en_morris_archive/summary.json"
        data = read_json(path)
        data["items"].append(data["items"][0])
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "duplicate selection"):
            build(self.base, self.root)


def read_json(path):
    return json.loads(path.read_text())


if __name__ == "__main__":
    unittest.main()
