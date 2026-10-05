# Fiona comment fixes — 5 October 2026

All new findings are soft: `phrase_ban`, `stylistic_repeat`, `judgment_label`,
`duplicate_topic`, `verify_source`. They never change draft readiness to a hard
failure. Style/topic findings share one additional compose rewrite, with combined
instructions. A failed rewrite, invalid claim ledger, guard regression or no
improvement retains the original; judgment labels are then stripped mechanically.
Judgment content and ordinary first-person opinion sentences remain allowed.

History stores the last 30 finalized bodies per persona, including bodies with
warnings. Default: `/workspace/x/fd_draft_history/{persona_id}.jsonl`; on an
unwritable directory: `live/store/recent_drafts/{persona_id}.jsonl` (ignored).
Checks use Chinese 4–6 character runs, English three-word phrases and seeded
multiword templates; closing similarity uses Jaccard over normalized style grams.
Numbers, dates, tickers, bound metric names and supplied fact-unit phrases are
excluded. Topic overlap uses stance subject or ticker overlap ≥0.7 within 36 hours;
explicit update/contrast/continuation markers permit another beat. These are
heuristics: human review should calibrate false positives, especially untranslated
company/metric names and English common phrases. History writes are best-effort;
concurrent writers for the same persona should be serialized by the caller.

Small `live/personas/posting_habits/*.json` cards contain aggregate length shares,
thread metadata rate, short intermediate-line punctuation share and sample IDs.
No donor text is included. Missing donors produce a documented Fiona default.
`live.posting_habits.write_card(persona)` refreshes a card from local donor files.
Metadata-based thread rate can undercount threads when scraping omitted thread
IDs. Compose includes habits/format guidance under the existing emotion payload
switch; `emotion_contract=False` keeps historical payload fields stable. Short
punchy posts prefer line breaks without intermediate periods; alternate shorts
with longer threads. The allowed opinion-marker list no longer includes my read.

Investing philosophy retrieves up to two Morris exemplars from the existing
ignored `runs/content_batch_v2/source_selection/en_morris_archive/selected_sources.json`
and `runs/content_workbench_v1/morris/sources.json` archives. English text is
preferred. ZH rhythm examples require `exemplar_retrieval.include_morris=true`;
EXEMPLAR_RULE still forbids copying wording or using exemplar facts. Untagged
`x_Morris_LT` / `Morris_LT` source records are accepted for content retrieval;
normal freshness filters still apply. No source corpus is uploaded and the
Morris archive account is unchanged.

Source caution deliberately uses an absolute heuristic, not peer outlier
statistics: source-bound quarterly USD revenue/guidance ≥$40 billion warns for
human verification. Micron $61.5 billion revenue/guidance also warns when found
in the body or units, even without a period. Trusted-source number-check bypass
cannot suppress this warning. No replacement number is generated. This is a
review hint, not a claim that all quarterly figures above the threshold are wrong.

Validation uses offline fake clients and isolated temporary history. The old
recorded fixture hashes remain unchanged; its adapter removes only newly seeded
avoid phrases when reproducing the historical request. No live Gemini batch.

Focused validation: 94 passed across `test_anti_repeat_oct5`, `test_qa_levels`,
`test_compose`, `test_compose_recorded`, `test_donor_exemplars`,
`test_emotion_contract`, `test_thesis_grounding`, `test_compose_retry_budget`.
After the final habit-card/routing tweaks, all 22 new tests passed again.
Full suite was not rerun; no claim about the existing 22 baseline failures.
