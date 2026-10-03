"""Offline contract tests; the fake client is not content-quality evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from live.account_source_adaptation import adapt_source, execution_failed, execution_failure, fidelity_hold
from live.distillation import CHECKS


ZH = "判断是否有效，需要反复测试并观察反馈。一次成功并不能证明方法可靠。"
EN = "A judgment needs repeated testing and feedback. One success does not prove that a method is reliable."


def source(text=ZH, author="Morris_LT", language="zh"):
    return {"id": "source-fixture", "source_id": "x_" + author,
            "original_text": text, "author_name": author, "author_handle": author,
            "url": "https://x.com/" + author + "/status/123", "source_language": language,
            "published_at": "2024-07-01T00:00:00+00:00", "content_complete": True,
            "post_type": "original", "source_type": "x", "synthetic": True}


class FakeClient:
    def __init__(self, account="en_morris_archive", text=EN, overrides=None):
        self.account, self.text = account, text
        self.overrides = overrides or {}
        self.calls = []

    def __call__(self, stage, messages, max_tokens):
        payload = json.loads(messages[1]["content"])
        self.calls.append((stage, payload))
        if stage == "routing":
            value = {"decision": "MOVE", "worth_moving": True, "account_id": self.account,
                     "confidence": .9, "reason": "TEST DOUBLE: audience fit"}
        elif stage == "selection":
            value = {"paragraph_ids": [p["paragraph_id"] for p in payload["paragraphs"]],
                     "reason": "TEST DOUBLE: complete unit", "dependencies_complete": True,
                     "needs_source": False}
        elif stage == "evergreen_gate":
            value = {"decision": "ACCEPT", "reason": "TEST DOUBLE: timeless framework",
                     "timeless_or_still_valid": True, "identity_resolved": True,
                     "personal_or_expired_premise_required": False,
                     "requires_current_verification": False, "verified_evidence_ids": [],
                     "source_quotes": [payload["selected_passages"][0]["exact_text"]]}
        elif stage == "source_hygiene":
            value = {"hygiene_decisions": [{"annotation_id": a["id"], "action": "retain",
                     "reason": "TEST DOUBLE: required source meaning"} for a in payload["annotations"]]}
        elif stage == "translation":
            value = {"segments": [{"paragraph_id": p["paragraph_id"], "text": self.text}
                                   for p in payload["selected_passages"]]}
        elif stage == "localization":
            value = {"edits": [], "added_background": []}
        elif stage == "qa":
            value = {"selection_context_complete": True, "confidence": .9,
                     "checks": [{"paragraph_id": p["paragraph_id"], **dict.fromkeys(CHECKS, True),
                                 "evidence": "TEST DOUBLE; no human or model semantic evaluation"}
                                for p in payload["selection"]["passages"]], "findings": []}
        else:
            raise AssertionError(stage)
        if stage in self.overrides:
            override = self.overrides[stage]
            value = override(value, payload) if callable(override) else override
        return {"text": json.dumps(value, ensure_ascii=False), "finish_reason": "stop",
                "model": "TEST_DOUBLE", "usage": None}


class AccountSourceAdaptationTests(unittest.TestCase):
    def test_completed_model_schema_failure_is_distinct_from_source_contract(self):
        saved = {'draft_status':'blocked', 'execution_failure': {'stage':'selection','code':'source_contract','error_type':'ContractError'},
            'attempt': {'stage':'selection','why':'selection: ContractError',
                        'model_responses':[{'stage':'selection','finish_reason':'stop','text':'{"paragraph_ids":["P1"]}'}]}}
        frozen = copy.deepcopy(saved)
        self.assertEqual(execution_failure(saved)['code'], 'model_response_contract')
        self.assertEqual(saved, frozen)
        saved['attempt']['model_responses'] = []
        self.assertEqual(execution_failure(saved)['code'], 'source_contract')

    def test_annotation_version_change_uses_frozen_inputs_with_current_qa(self):
        from live import source_hygiene
        parent = self.qa_failed_parent()
        original = copy.deepcopy(parent)
        annotate = source_hygiene.annotate
        def revised(source):
            return {**annotate(source), 'version':'TEST_ONLY_NEW_ANNOTATION_VERSION'}
        client = FakeClient()
        with patch('live.source_hygiene.annotate', side_effect=revised):
            result = adapt_source(parent['source_adaptation']['source'], 'en_morris_archive', self.directory/'version-followup',
                client=client, follow_up_of=parent['id'], checkpoint=parent,
                account_context=parent['source_adaptation']['attempt']['account_context'])
        self.assertEqual(result['draft_status'], 'draft_ready', result['why'])
        self.assertEqual([stage for stage,_ in client.calls], ['qa'])
        self.assertEqual(result['source']['source_hygiene'], parent['source_adaptation']['source']['source_hygiene'])
        self.assertEqual(result['localization'], parent['source_adaptation']['localization'])
        self.assertEqual(parent, original)

    def test_deterministic_qa_failure_is_fidelity_hold_not_execution_failure(self):
        row = source(ZH + "成功率为 25%。")
        result, _ = self.run_source(row, client=FakeClient(text=EN + " The success rate is 50%."))
        self.assertEqual(result["draft_status"], "needs_review")
        self.assertTrue(fidelity_hold(result))
        self.assertIsNone(result["execution_failure"])
        self.assertFalse(execution_failed({"source_adaptation": result}))
        self.assertNotEqual(result["final_draft"], "")

    def qa_failed_parent(self):
        class IncompleteQA(FakeClient):
            def __call__(self, stage, messages, max_tokens):
                value = super().__call__(stage, messages, max_tokens)
                if stage == "qa":
                    value["finish_reason"] = "length"
                return value
        result, _ = self.run_source(client=IncompleteQA(), account_context={"as_of": "2026-09-27T12:00:00+00:00"})
        self.assertEqual(result["execution_failure"]["stage"], "qa")
        return {"id": "original-qa-failure", "status": "execution_failed", "source_adaptation": result}

    def test_qa_checkpoint_only_calls_qa_and_preserves_exact_candidate(self):
        parent = self.qa_failed_parent()
        original = copy.deepcopy(parent)
        client = FakeClient()
        result = adapt_source(parent["source_adaptation"]["source"], "en_morris_archive", self.directory / "followup",
            client=client, follow_up_of=parent["id"], checkpoint=parent,
            account_context=parent["source_adaptation"]["attempt"]["account_context"])
        self.assertEqual(result["draft_status"], "draft_ready", result["why"])
        self.assertEqual([s for s, _ in client.calls], ["qa"])
        for field in ("selection", "translation", "localization", "final_draft"):
            self.assertEqual(result[field], parent["source_adaptation"][field])
        self.assertEqual(result["execution_checkpoint"]["parent_run_id"], parent["id"])
        self.assertEqual(parent, original)

    def test_qa_checkpoint_changed_source_never_falls_back_to_regeneration(self):
        parent = self.qa_failed_parent()
        row = {**parent["source_adaptation"]["source"], "title": "Changed source title"}
        client = FakeClient()
        result = adapt_source(row, "en_morris_archive", self.directory / "mismatch", client=client,
            follow_up_of=parent["id"], checkpoint=parent,
            account_context=parent["source_adaptation"]["attempt"]["account_context"])
        self.assertFalse(client.calls)
        self.assertEqual(result["execution_failure"]["code"], "checkpoint_mismatch")
        self.assertEqual(result["final_draft"], parent["source_adaptation"]["final_draft"])
        self.assertEqual(result["machine_fidelity"]["status"], "not_passed")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def run_source(self, row=None, account="en_morris_archive", client=None, **kwargs):
        client = client or FakeClient(account)
        return adapt_source(row or source(), account, self.directory, client, **kwargs), client

    def test_morris_is_direct_translation_not_new_commentary(self):
        row = source()
        original = copy.deepcopy(row)
        result, client = self.run_source(row)
        self.assertEqual(result["status"], "draft_ready", result)
        self.assertEqual(result["final_draft"], EN)
        self.assertEqual(result["target_language"], "en")
        self.assertEqual(result["human_review"]["status"], "pending")
        self.assertEqual(result["machine_fidelity"]["status"], "pass")
        self.assertEqual(row, original)
        calls = dict(client.calls)
        self.assertEqual([a["id"] for a in calls["routing"]["eligible_accounts"]], ["en_morris_archive"])
        self.assertEqual(calls["translation"]["selected_passages"][0]["exact_text"], ZH)
        self.assertNotIn("brief", calls["translation"])
        self.assertNotIn("value_beyond_translation", calls["routing"])
        self.assertTrue(Path(result["attempt_ref"]).is_file())
        self.assertTrue(Path(result["result_path"]).is_file())

    def test_same_language_is_refused_without_model_calls(self):
        # P0-1: same-language material never passes through as a "translation".
        result, client = self.run_source(source(ZH, "macro_writer"), "zh_macro")
        self.assertNotEqual(result["status"], "draft_ready", result)
        self.assertFalse(result.get("final_draft"))
        self.assertEqual(dict(client.calls), {})

    def test_english_to_chinese_keeps_language_owned_by_account(self):
        client = FakeClient("zh_industry", ZH)
        result, client = self.run_source(source(EN, "industry_writer", "en"), "zh_industry", client)
        self.assertEqual(result["status"], "draft_ready", result)
        self.assertEqual((result["source_language"], result["target_language"]), ("en", "zh"))
        self.assertEqual(result["final_draft"], ZH)

    def test_none_and_skip_stop_all_writing(self):
        for decision in ("NONE", "SKIP"):
            with self.subTest(decision=decision):
                client = FakeClient(overrides={"routing": lambda v, p: {
                    **v, "decision": decision, "worth_moving": decision == "NONE", "account_id": None}})
                result, client = self.run_source(client=client)
                self.assertEqual(result["status"], "skipped")
                self.assertEqual(result["account_id"], "en_morris_archive")
                self.assertEqual(result["final_draft"], "")
                self.assertEqual([s for s, _ in client.calls], ["routing"])

    def test_wrong_account_or_language_cannot_escape_inbox(self):
        for changes in ({"account_id": "zh_macro"}, {"target_language": "zh"}):
            client = FakeClient(overrides={"routing": lambda v, p: {**v, **changes}})
            result, client = self.run_source(client=client)
            self.assertEqual(result["status"], "held")
            self.assertEqual([s for s, _ in client.calls], ["routing"])
            self.assertEqual(result["final_draft"], "")

    def test_morris_source_identity_is_not_inferred_from_source_id(self):
        row = source(author="someone_else")
        row["source_id"] = "x_Morris_LT"
        result, client = self.run_source(row)
        self.assertEqual(result["status"], "skipped")
        self.assertFalse(client.calls)

    def test_incomplete_source_holds_before_any_model_call(self):
        row = source()
        row["content_complete"] = False
        result, client = self.run_source(row)
        self.assertEqual(result["draft_status"], "needs_source")
        self.assertEqual(result["account_id"], "en_morris_archive")
        self.assertFalse(client.calls)

    def test_morris_personal_premise_cannot_be_stripped_to_pass(self):
        for change in ({"personal_or_expired_premise_required": True},
                       {"requires_current_verification": True}, {"identity_resolved": False}):
            client = FakeClient(overrides={"evergreen_gate": lambda v, p: {**v, **change}})
            result, client = self.run_source(client=client)
            self.assertEqual(result["status"], "held")
            self.assertEqual(result["source"]["original_text"], ZH)
            self.assertNotIn("translation", dict(client.calls))
            self.assertNotIn("localization", dict(client.calls))

    def test_morris_gate_rejects_invented_or_unverified_current_evidence(self):
        client = FakeClient(overrides={"evergreen_gate": lambda v, p: {
            **v, "requires_current_verification": True, "verified_evidence_ids": ["fake"]}})
        result, client = self.run_source(client=client, account_context={"current_evidence": [
            {"id": "fake", "text": "Not independently checked", "url": "https://example.test/",
             "as_of": "2026-09-30", "verification_status": "unreviewed"}]})
        self.assertEqual(result["status"], "held")
        self.assertNotIn("translation", dict(client.calls))

    def test_machine_failure_keeps_exact_candidate_visible_for_review(self):
        def bad_qa(value, payload):
            value["checks"][0]["stance_preserved"] = False
            return value
        client = FakeClient(overrides={"qa": bad_qa})
        result, client = self.run_source(client=client)
        self.assertEqual(result["status"], "held")
        self.assertEqual(result["final_draft"], EN)
        self.assertEqual(result["publishable_text"], "")
        self.assertEqual(result["human_review"]["status"], "pending")
        self.assertEqual(result["machine_fidelity"]["status"], "not_passed")

    def test_long_selection_uses_exact_full_paragraphs_not_summary(self):
        # P0-1: cross-language fixture (same-language sources are refused at route).
        first = "Industry supply needs gradual verification, and technology paths need real demand. " * 75
        row = source(first + "\n\n" + EN, "industry_writer", "en")
        client = FakeClient("zh_industry", ZH, overrides={"selection": lambda v, p: {**v, "paragraph_ids": ["P2"]}})
        result, client = self.run_source(row, "zh_industry", client)
        self.assertEqual(result["status"], "draft_ready", result)
        self.assertEqual(result["final_draft"], ZH)
        self.assertEqual(result["selection"]["passages"][0]["start"], len(first) + 2)
        self.assertEqual(dict(client.calls)["localization"]["selected_passages"][0]["exact_text"], EN)
        self.assertEqual(dict(client.calls)["qa"]["source"]["original_text"], row["original_text"])

    def test_followup_preserves_attempt_identity_and_context_without_auto_approval(self):
        first, _ = self.run_source()
        context = {"as_of": "2026-09-30T00:00:00+00:00", "snapshot": {"id": "s1"},
                   "human_feedback": [{"reason": "Keep the original rhythm"}]}
        follow, _ = self.run_source(follow_up_of=first["id"], account_context=context)
        self.assertNotEqual(first["id"], follow["id"])
        self.assertEqual(follow["follow_up_of"], first["id"])
        self.assertEqual(follow["attempt"]["account_context"], context)
        self.assertEqual(follow["human_review"]["status"], "pending")
        self.assertTrue(Path(first["attempt_ref"]).exists())
        self.assertTrue(Path(follow["attempt_ref"]).exists())

    def test_required_media_remains_a_hard_preflight_blocker(self):
        row = source()
        row["media_dependencies"] = [{"kind": "chart", "required": True, "url": "https://example.test/chart.png"}]
        result, client = self.run_source(row)
        self.assertEqual(result["draft_status"], "needs_source")
        self.assertFalse(client.calls)
        self.assertEqual(result["source"]["media_dependencies"], row["media_dependencies"])

    def test_uncertain_media_survives_routing_selection_and_private_disposition(self):
        first = "This paragraph discusses an industry constraint and stays as selection context. " * 90
        row = source(first + "\n\n" + EN, "industry_writer", "en")
        dependency = {"kind": "chart", "required": None, "status": "uncertain_dependency",
                      "selection_review_required": True, "url": "https://example.test/chart.png"}
        row["media_dependencies"] = [dependency]
        original = copy.deepcopy(row)
        client = FakeClient("zh_industry", ZH, overrides={
            "selection": lambda v, p: {**v, "paragraph_ids": ["P2"]},
            "source_hygiene": lambda v, p: {"hygiene_decisions": [
                {"annotation_id": a["id"], "action": "out_of_scope",
                 "reason": "TEST DOUBLE: selected second paragraph is a complete independent argument"}
                for a in p["annotations"]]}})
        result, client = self.run_source(row, "zh_industry", client)
        self.assertEqual(result["status"], "draft_ready", result)
        self.assertEqual(row, original)
        for stage in ("routing", "selection"):
            media = dict(client.calls)[stage]["source"]["context_items"][0]
            self.assertEqual(media["dependency"], dependency)
            self.assertTrue(media["selection_review_required"])
        self.assertFalse(result["source"]["media_dependencies"])
        self.assertEqual(result["attempt"]["hygiene_decisions"][0]["action"], "out_of_scope")
        self.assertEqual(result["final_draft"], ZH)
        # Re-importing the normalized source must retain the private annotation.
        second, second_client = self.run_source(result["source"], "zh_industry", client=FakeClient(
            "zh_industry", overrides=client.overrides))
        self.assertEqual(second["source_version"], result["source_version"])
        self.assertIn("source_hygiene", dict(second_client.calls))

    def test_short_post_with_indispensable_uncertain_media_can_hold_at_route(self):
        row = source()
        row["media_dependencies"] = [{"kind": "chart", "required": None,
                                      "status": "uncertain_dependency"}]
        client = FakeClient(overrides={"routing": lambda v, p: {
            **v, "decision": "NEEDS_SOURCE", "account_id": None,
            "reason": "TEST DOUBLE: argument depends on missing chart"}})
        result, client = self.run_source(row, client=client)
        self.assertEqual(result["draft_status"], "needs_source")
        self.assertEqual([s for s, _ in client.calls], ["routing"])
        self.assertEqual(dict(client.calls)["routing"]["source"]["context_items"][0]["kind"],
                         "unresolved_media_dependency")
        self.assertFalse(result["final_draft"])

    def test_current_evidence_rejects_duplicate_ids_naive_dates_and_future_dates(self):
        evidence = {"id": "e1", "text": "TEST DOUBLE evidence", "url": "https://example.test/evidence",
                    "as_of": "2026-09-29T12:00:00+00:00", "verification_status": "verified"}
        cases = [[evidence, evidence], [{**evidence, "as_of": "2026-09-29T12:00:00"}],
                 [{**evidence, "as_of": "2026-10-01T00:00:00+00:00"}],
                 [{**evidence, "verified_at": "2026-10-01T00:00:00+00:00"}]]
        for rows in cases:
            with self.subTest(evidence=rows):
                result, client = self.run_source(account_context={
                    "as_of": "2026-09-30T00:00:00+00:00", "current_evidence": rows})
                self.assertEqual(result["status"], "held")
                self.assertNotIn("evergreen_gate", dict(client.calls))
                self.assertNotIn("translation", dict(client.calls))

    def test_dated_current_evidence_retains_exact_refs_without_inventing_human_review(self):
        client = FakeClient(overrides={"evergreen_gate": lambda v, p: {
            **v, "requires_current_verification": True, "verified_evidence_ids": ["e1"]}})
        result, client = self.run_source(client=client, account_context={
            "as_of": "2026-09-30T00:00:00+00:00", "current_evidence": [{
                "id": "e1", "text": "TEST DOUBLE only; this is not factual evaluation evidence",
                "url": "https://example.test/evidence", "as_of": "2026-09-29T20:00:00-04:00",
                "verification_status": "verified"}]})
        self.assertEqual(result["status"], "draft_ready", result)
        self.assertEqual(result["evergreen_gate"]["verified_evidence_ids"], ["e1"])
        self.assertEqual(result["human_review"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
