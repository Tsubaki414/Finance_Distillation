"""Offline, rerunnable review export for the three-account content batch.

Reads completed summary/adaptation artifacts. Never generates, edits, publishes,
clears machine holds, or writes human results. Run after account summaries settle:
  .venv/bin/python -B scripts/build_content_batch_packet.py
Use --allow-partial only for a visibly incomplete work-in-progress export.
"""
import argparse
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS = ("en_morris_archive", "zh_macro", "zh_industry")
VERSION = "content-review-packet-v1"
BLIND_SEED = "content-batch-v2-editorial-naturalness-2026-09-30"
TOPICS = {
    "risk_wealth": ("risk", "wealth", "rich", "gambling", "compound", "freedom", "风险", "财富", "自由"),
    "decisions": ("decision", "probability", "uncertain", "learning", "cognitive", "判断", "概率", "认知"),
    "business": ("startup", "entrepreneur", "business", "service", "power-law", "failure", "创业", "服务", "幂律"),
    "inflation": ("inflation", "pce", "cpi", "prices", "通胀", "物价"),
    "employment": ("employment", "labor", "labour", "payroll", "就业", "非农", "劳动力"),
    "policy": ("fed", "monetary", "fiscal", "rates", "election", "政策", "利率", "选举"),
    "flows": ("flow", "liquidity", "positioning", "repo", "treasury", "流动性", "资金", "仓位", "国债"),
    "memory": ("memory", "hbm", "dram", "nand", "内存", "存储", "闪迪"),
    "packaging": ("packaging", "osat", "cowos", "tsmc", "封装", "台积电"),
    "optical": ("optical", "interconnect", "bandwidth", "光通信", "光模块", "带宽"),
    "inference": ("inference", "latency", "cerebras", "推理", "延迟"),
    "datacenter": ("datacenter", "data center", "power", "rack", "cpu", "数据中心", "电力", "机架"),
    "robotics": ("robot", "unitree", "actuator", "机器人", "宇树"),
    "earnings": ("earnings", "revenue", "margin", "capacity", "supply", "财报", "收入", "毛利", "产能", "供给"),
}


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def word_count(text):
    text = re.sub(r"https?://\S+", "", text)
    return len(re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*", text, re.UNICODE))


def measure(text, language):
    return word_count(text) if language == "en" else len(text)


def tags(text):
    lowered = text.lower()
    return {name for name, terms in TOPICS.items() if any(t in lowered for t in terms)}


def blank_review():
    return {"status": "pending", "edit_class": None, "edit_class_options": ["unchanged", "minor", "major", "reject"],
            "reasons": [], "error_types": [], "severity": None, "edited_text": None,
            "reviewer": None, "reviewed_at": None}


def relative(path, root):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(root.resolve()))
    except ValueError:
        return str(path)


def baseline_info(data, language):
    if language == "en":
        stats = data.get("verified_length_stats", {})
    else:
        stats = data.get("unicode_character_summary") or data.get("statistics", {}).get("unicode_codepoints", {})
    return {"unit": "words" if language == "en" else "Unicode characters including whitespace",
            "statistics": stats, "sampling_limitations": data.get("limitations") or data.get("limits") or
            [data.get("representativeness", "Convenience sample; not a hard length limit")],
            "not_a_hard_cap": True}


def unique_risks(adaptation):
    qa = adaptation.get("machine_fidelity", {}).get("qa", {})
    items = list(adaptation.get("risks") or []) + list(qa.get("findings") or [])
    seen, result = set(), []
    for item in items:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def attach_agent_observations(draft, observations):
    """Private review notes are applicable only to the exact inspected output."""
    draft["agent_observations"] = [note for note in observations
        if note.get("selection_id") == draft["selection_id"]
        and note.get("run_id") == draft["run_id"]
        and note.get("draft_sha256") == draft["draft_sha256"]
        and note.get("source_hash") == draft["source"]["source_hash"]]


def bind_draft(outcome, curated, adaptation, language, baseline, adaptation_path):
    """Fail closed on draft/source mismatch, not on a correctly recorded QA hold."""
    source = adaptation["source"]
    text = source["original_text"]
    expected = curated["source"]["original_text"]
    if text != expected or digest(text) != outcome["source_hash"]:
        raise ValueError("Source body/hash mismatch: " + outcome["selection_id"])
    draft = outcome.get("final_draft")
    if not isinstance(draft, str) or not draft.strip():
        raise ValueError("Cannot export an empty draft")
    if draft != adaptation.get("final_draft"):
        raise ValueError("Draft differs from adaptation: " + outcome["selection_id"])
    if outcome.get("generation_origin") != "automated_pipeline":
        raise ValueError("Non-automatic draft cannot enter this cohort")
    if adaptation.get("generation_origin", "automated_pipeline") != "automated_pipeline":
        raise ValueError("Adaptation origin conflicts with automatic outcome")
    if adaptation.get("account_id", outcome["account_id"]) != outcome["account_id"] or \
            adaptation.get("target_language", language) != language:
        raise ValueError("Adaptation account/language mismatch")
    passages = adaptation.get("selection", {}).get("passages", [])
    if not passages:
        raise ValueError("Missing exact selected passages")
    previous = -1
    for passage in passages:
        start, end = passage["start"], passage["end"]
        if start < previous or end < start or text[start:end] != passage["exact_text"]:
            raise ValueError("Selected source range mismatch")
        previous = end
    n = measure(draft, language)
    stats = baseline["statistics"]
    outliers = []
    if stats.get("p90") is not None and n > stats["p90"]:
        outliers.append("Above observed p90; inspect fit without automatically cutting source reasoning")
    if stats.get("min") is not None and n < stats["min"]:
        outliers.append("Below observed minimum; check whether a complete useful argument survived")
    info = {k: source.get(k) for k in ("source_id", "author_name", "author_handle", "url", "title", "published_at",
            "fetched_at", "source_language", "content_kind", "content_complete", "extraction_status", "raw_import_ref")}
    return {"selection_id": outcome["selection_id"], "account_id": outcome["account_id"],
            "run_id": outcome["run_id"], "follow_up_of": outcome.get("follow_up_of"),
            "generation_origin": outcome["generation_origin"],
            "generation_protocol": adaptation.get("generation_protocol"),
            "prompt_versions": adaptation.get("batch_prompt_versions", {}),
            "source": {**info, "original_text": text, "source_hash": digest(text),
                       "selected_passages": passages, "completeness_proof": curated.get("completeness_proof"),
                       "context_items": source.get("context_items", [])},
            "final_draft": draft, "draft_sha256": digest(draft), "language": language,
            "length": {"value": n, "unit": baseline["unit"], "unicode_characters": len(draft),
                       "words": word_count(draft), "observed_outliers": outliers},
            "machine": {"outcome_status": outcome["status"], "pass": outcome.get("machine_pass") is True,
                        "why": outcome.get("why"), "fidelity": adaptation.get("machine_fidelity", {}),
                        "does_not_establish_editorial_acceptance": True},
            "risks": unique_risks(adaptation), "human_review": blank_review(),
            "adaptation_artifact": str(adaptation_path), "adaptation_sha256": digest(Path(adaptation_path).read_bytes()),
            "topic_context": " ".join(str(curated.get(k) or "") for k in
                                      ("topic", "working_topic", "selection_reason")) + " " + str(info.get("title") or "")}


def reference_text(reference):
    text = reference.get("original_text", reference.get("text"))
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Reference has no exact body")
    expected_hash = reference.get("text_sha256") or reference.get("body_sha256")
    if not expected_hash or expected_hash != digest(text):
        raise ValueError("Reference body/hash mismatch")
    return text


def match_references(drafts, references, language):
    """Minimum-cost unique topic/length matching; never rewrites a reference."""
    eligible, seen = [], set()
    for r in references:
        if r.get("exclusion_reason") or r.get("baseline_eligible") is False:
            continue
        lang = r.get("language", r.get("source_language", language))
        if lang != language:
            continue
        body = reference_text(r)
        if digest(body) in seen:
            raise ValueError("Duplicate reference body")
        seen.add(digest(body))
        eligible.append(r)
    if len(eligible) < len(drafts):
        raise ValueError("Not enough unique same-language references")
    if len(eligible) > 20:
        raise ValueError("Review curated reference list before expanding bounded matcher")
    costs = []
    evidence = []
    for d in drafts:
        dt = tags(d["topic_context"] + " " + d["final_draft"])
        row, details = [], []
        for r in eligible:
            rt = tags(" ".join(str(r.get(k) or "") for k in
                      ("topic", "topic_match_reason", "selection_reason", "selection_basis")) + " " + reference_text(r))
            overlap = sorted(dt & rt)
            similarity = len(dt & rt) / len(dt | rt) if dt | rt else 0
            ratio = max(1, measure(d["final_draft"], language)) / max(1, measure(reference_text(r), language))
            score = 2 * (1 - similarity) + abs(math.log(ratio))
            row.append(score)
            details.append({"shared_topic_tags": overlap, "draft_to_reference_length_ratio": round(ratio, 3),
                            "topic_match_method": "Fixed bilingual keyword categories; approximate, not a human judgment",
                            "topic_match_weak": not overlap, "length_mismatch_over_2x": ratio > 2 or ratio < .5})
        costs.append(row)
        evidence.append(details)

    @lru_cache(None)
    def solve(i, used):
        if i == len(drafts):
            return 0.0, ()
        choices = []
        for j in range(len(eligible)):
            if not used & (1 << j):
                score, path = solve(i + 1, used | (1 << j))
                choices.append((costs[i][j] + score, (j,) + path))
        return min(choices)

    _, chosen = solve(0, 0)
    return [(eligible[j], evidence[i][j]) for i, j in enumerate(chosen)]


def blind_packet(account, drafts, references, language):
    matched = match_references(drafts, references, language)
    entries, private = [], []
    for draft, (reference, match) in zip(drafts, matched):
        for kind, identity, text, metadata in [
            ("automatic_draft", draft["run_id"], draft["final_draft"], {"selection_id": draft["selection_id"],
                "run_id": draft["run_id"], "machine_status": draft["machine"]["outcome_status"],
                "draft_sha256": draft["draft_sha256"]}),
            ("public_reference", reference["reference_id"], reference_text(reference), {"reference": reference})]:
            opaque = digest(BLIND_SEED + "|" + account + "|" + kind + "|" + identity + "|" + digest(text))[:12]
            entries.append({"opaque_id": opaque, "text": text,
                            "response": {"native_expression": None, "editorial_quality": None,
                                         "obvious_generated_style": None, "notes": None}})
            private.append({"opaque_id": opaque, "kind": kind, "body_sha256": digest(text), **metadata,
                            "matched_selection_id": draft["selection_id"], "matching": match})
    entries.sort(key=lambda x: digest(BLIND_SEED + "|order|" + x["opaque_id"]))
    return ({"schema_version": "editorial-blind-participant-v1", "language": language,
             "instructions": "Read each post as a separate piece. Judge natural expression, useful reasoning and obvious generated style. Leave uncertain answers blank; do not guess a specific person's identity.",
             "items": entries},
            {"account_id": account, "study_status": "prepared_not_administered", "human_results_count": 0,
             "public_reference_does_not_prove_human_only_authorship": True,
             "matching_method": "Unique assignment minimizing 2*(1-topic Jaccard)+abs(log length ratio); fixed bilingual topic categories",
             "items": private})


def build(base, root=ROOT, allow_partial=False):
    accounts, manifests, gaps = [], {}, []
    for account in ACCOUNTS:
        folder = base / "source_selection" / account
        paths = {"sources": folder / "selected_sources.json", "references": folder / "references.json",
                 "baseline": folder / "length_baseline.json", "summary": base / "outcomes" / account / "summary.json"}
        docs = {}
        for key, path in paths.items():
            if not path.exists():
                if key == "summary" and allow_partial:
                    docs[key] = {"items": []}
                    gaps.append(account + ": summary missing")
                    continue
                raise ValueError("Missing input: " + str(path))
            raw = path.read_bytes()
            manifests[relative(path, root)] = digest(raw)
            docs[key] = json.loads(raw)
        source_map = {r["selection_id"]: r for r in docs["sources"]["sources"]}
        language = "en" if account == "en_morris_archive" else "zh"
        baseline = baseline_info(docs["baseline"], language)
        observation_path = folder / "agent_observations.json"
        observations = []
        if observation_path.exists():
            manifests[relative(observation_path, root)] = digest(observation_path.read_bytes())
            observations = read(observation_path).get("observations", [])
        drafts, no_draft, seen = [], [], set()
        for outcome in docs["summary"].get("items", []):
            selection_id = outcome["selection_id"]
            if selection_id in seen:
                raise ValueError("Summary contains duplicate selection identity")
            seen.add(selection_id)
            if outcome.get("account_id") != account:
                raise ValueError("Cross-account outcome in summary")
            if not outcome.get("final_draft", "").strip():
                no_draft.append({k: outcome.get(k) for k in ("selection_id", "run_id", "status", "why", "follow_up_of")})
                continue
            path = Path(outcome["adaptation_path"])
            if not path.is_absolute():
                path = root / path
            adaptation = read(path)
            draft = bind_draft(outcome, source_map[selection_id], adaptation, language, baseline, path)
            attach_agent_observations(draft, observations)
            drafts.append(draft)
            manifests[relative(path, root)] = digest(path.read_bytes())
        if len(drafts) != 5:
            gaps.append(f"{account}: {len(drafts)}/5 exact automatic drafts")
        if len(drafts) > 5:
            raise ValueError("More than five drafts in authoritative summary; select cohort explicitly")
        participant, key = blind_packet(account, drafts, docs["references"]["references"], language)
        reference_limits = docs["references"].get("limitations") or [docs["references"].get("qualification", "")]
        key["limitations"] = [x for x in reference_limits if x] + [
            "Reference selection and topic/length matching are agent-curated, pending human review.",
            "No source/QA labels are appended to participant bodies; names or links already present in exact public copy may still make an item recognizable.",
            "Historical dates, platform genre, contextual replies and length can confound origin guesses. Do not interpret this as a controlled human-versus-AI authorship study.",
            "Machine holds remain in the generated cohort. Blind opinion cannot clear fidelity holds or authorize publication."]
        accounts.append({"account_id": account, "language": language, "drafts": drafts, "no_draft_attempts": no_draft,
                         "baseline": baseline, "reference_limits": reference_limits,
                         "blind_participant": participant, "blind_private_key": key})
    if gaps and not allow_partial:
        raise ValueError("Incomplete packet: " + "; ".join(gaps))
    count = sum(len(a["drafts"]) for a in accounts)
    return {"schema_version": VERSION, "status": "complete_15_drafts_pending_human" if not gaps else "partial_pending_generation",
            "draft_count": count, "requested_drafts": 15, "gaps": gaps, "human_reviews": 0,
            "machine_pass_is_editorial_acceptance": False, "publishing_enabled": False,
            "input_sha256": manifests, "accounts": accounts}


def code_block(text):
    """Keep exact bytes between a fence longer than any original backtick run."""
    fence = "`" * max(3, max((len(s) for s in re.findall(r"`+", text)), default=0) + 1)
    return fence + "text\n" + text + "\n" + fence


def render_review(packet):
    out = ["# Content acceptance review", "",
           f"{packet['draft_count']}/15 exact automatic drafts · human review pending · publication disabled.",
           "Machine fidelity and editorial quality are separate. Holds below are unchanged; no draft was polished for this packet.", "",
           "For the blind exercise, review only the participant file first; this packet and private key reveal identities.", ""]
    if packet["gaps"]:
        out += ["Incomplete: " + "; ".join(packet["gaps"]), ""]
    for account in packet["accounts"]:
        out += ["## " + account["account_id"], "", "Length reference: " + json.dumps(account["baseline"]["statistics"], ensure_ascii=False),
                "Observed lengths are a comparison, not a cap or editorial-quality score.", ""]
        for draft in account["drafts"]:
            source = draft["source"]
            out += ["### " + draft["selection_id"], "", "**Source** · " + str(source.get("author_name") or "Publisher attribution only") +
                    " · " + str(source.get("published_at") or "date unknown") + " · " + str(source.get("url") or ""), "",
                    "Scope: " + str(source.get("content_kind") or source.get("extraction_status")) +
                    ". Exact selected passages below; full available source and parent provenance are in packet.json.", ""]
            for passage in source["selected_passages"]:
                out += [f"{passage['paragraph_id']} · source characters {passage['start']}–{passage['end']}", "", code_block(passage["exact_text"]), ""]
            out += ["**Final draft — exact automatic output**", "", code_block(draft["final_draft"]), "",
                    "**Review risks**", "", f"Machine: **{draft['machine']['outcome_status']}** · fidelity pass: {draft['machine']['pass']} · human: pending.",
                    f"Length: {draft['length']['value']} {draft['length']['unit']}.", ""]
            for item in draft["length"]["observed_outliers"]:
                out.append("- Length observation: " + item)
            for note in draft.get("agent_observations", []):
                out.append("- Agent observation, not human acceptance or a changed machine verdict: " + note["detail"])
            for risk in draft["risks"]:
                out.append("- Machine finding: " + json.dumps(risk, ensure_ascii=False))
            if not draft["risks"]:
                out.append("No machine finding recorded; this is not human content approval.")
            out += ["", "**Human review — leave blank until reviewed**", "",
                    "- Edit class: [ ] unchanged  [ ] minor  [ ] major  [ ] reject",
                    "- Reasons / recurring error types / severity:", "- Actual edited text:", "- Reviewer / date:", ""]
        if account["no_draft_attempts"]:
            out += ["No-draft attempts (not counted as completed content): " + json.dumps(account["no_draft_attempts"], ensure_ascii=False), ""]
    return "\n".join(out)


def write_packet(packet, output):
    output.mkdir(parents=True, exist_ok=True)
    public_packet = {**packet, "accounts": [{k: v for k, v in a.items() if not k.startswith("blind_")}
                                           for a in packet["accounts"]]}
    (output / "packet.json").write_text(json.dumps(public_packet, ensure_ascii=False, indent=2) + "\n")
    (output / "REVIEW_PACKET.md").write_text(render_review(packet))
    for account in packet["accounts"]:
        folder = output / "blind" / account["account_id"]
        folder.mkdir(parents=True, exist_ok=True)
        participant = account["blind_participant"]
        (folder / "participant.json").write_text(json.dumps(participant, ensure_ascii=False, indent=2) + "\n")
        lines = ["# Reading review", "", participant["instructions"], ""]
        for item in participant["items"]:
            lines += ["## " + item["opaque_id"], "", code_block(item["text"]), "",
                      "Natural expression: ___  Editorial quality: ___  Obvious generated style: ___", "Notes: ___", ""]
        (folder / "participant.md").write_text("\n".join(lines))
        (folder / "PRIVATE_ANSWER_KEY.json").write_text(json.dumps(account["blind_private_key"], ensure_ascii=False, indent=2) + "\n")
        (folder / "PRIVATE_LIMITATIONS.md").write_text("# Private matching limitations\n\n" +
            "\n".join("- " + str(x) for x in account["blind_private_key"]["limitations"]) + "\n\n" +
            "Human results: none. Public reference authors may use AI; publication does not establish human-only composition.\n\n" +
            "| Draft | Reference | Shared topic categories | Draft/reference length | Limit |\n| --- | --- | --- | ---: | --- |\n" +
            "\n".join("| " + x["matched_selection_id"] + " | " + x["reference"]["reference_id"] + " | " +
                ", ".join(x["matching"]["shared_topic_tags"]) + " | " + str(x["matching"]["draft_to_reference_length_ratio"]) +
                " | " + ("weak topic match; " if x["matching"]["topic_match_weak"] else "") +
                ("length differs by more than 2×" if x["matching"]["length_mismatch_over_2x"] else "approximate match only") + " |"
                for x in account["blind_private_key"]["items"] if x["kind"] == "public_reference") + "\n")


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--base", type=Path, default=ROOT / "runs/content_batch_v2")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    packet = build(args.base, allow_partial=args.allow_partial)
    output = args.output or args.base / "review"
    write_packet(packet, output)
    print(json.dumps({"status": packet["status"], "draft_count": packet["draft_count"],
                      "output": str(output), "gaps": packet["gaps"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
