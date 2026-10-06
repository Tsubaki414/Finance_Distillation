# Direction drift, continue-vs-revise rule, meta-continuation ban (2026-10-06)

Soft-only: nothing here blocks a draft or a ledger write.

## Why (P1-1 ledger dry-run, /workspace/x/ledger_p1_oct6)
- zh_macro day 2 kept the SAME direction (lower -> lower) but the model set `revises_view_id`
  because the horizon changed (prompt allowed revise on conviction/horizon change).
- en_macro day 2 cited the prior and wrote "Continuing the expectation ...", but the direction moved
  lower -> neutral without `revises_view_id`. `link_continuity` left it `fresh` with no finding
  (`ignores_prior` is silent once a prior is cited), so the ledger got a second current head for the
  same Fed topic.

## 1. Stance prompt rule (live/stance.py STANCE)
CONTINUE = same subject + same direction, even when horizon/conviction change or evidence is added:
no `revises_view_id`, cite the prior in `cited_prior_view_ids`; the system links `continues_view_id`
(still deterministic - model ids are never trusted). REVISE = direction changes or the core thesis is
replaced. Citing a prior with a different direction requires `revises_view_id`. The old "keep the same
call with a continuity phrase" wording is gone. A same-direction revise is still kept (core-thesis
changes are legitimate) but `continuity.same_direction = true` marks it for review.

## 2. `direction_drift_unmarked` + `drift_of_view_id` (live/view_ledger.py)
Design chosen (least invasive): a third deterministic link type next to continue/revise.
In `link_continuity`, when no same-direction prior matches, an on-topic current prior qualifies as a
drift parent when both directions are set, differ and are NOT opposite (opposite = flip, unchanged:
`contradicts_prior_view`), and the model cited it (`cited_prior_view_ids`), referenced it with a
meta-continuation phrase (`stance_scrub.meta_continuation`), or its subject overlap >= 0.4.
Then:
- stance gets `drift_of_view_id` and `continuity = {link: drift, view_id, from_direction, to_direction}`;
- `ViewLedger.drift_findings` adds SOFT `direction_drift_unmarked` (qa_levels SOFT + fix text);
- `record` writes `drift_of_view_id`; `current()` treats it like the other links (parent superseded),
  `lineage()` follows it. So the topic keeps ONE current head (the latest call) and the human sees a
  yellow flag asking to confirm the revise or keep the earlier direction.
Rejected alternatives: auto-setting `revises_view_id` (the system would assert a revise the model never
made, hiding the gap); flag-only with no link (keeps the duplicate current head that caused the issue).
Ledger rows always carry `drift_of_view_id` (null when unused); old rows lack it (= null).

## 3. Meta-continuation openers
EN: "Continuing the expectation/view/call…", "Continuing from my earlier…", "Following up on…",
"Building on my earlier…", "As I said/noted…", "As previously noted…", "To reiterate…".
ZH: 延续此前/之前的判断/观点/观察, 接着上次, 正如我之前说, 我之前就说过, 如前所述, 重申此前判断.
- Stance (`live/stance.py`): `scrub_account_view` strips such an opener clause up to its first comma
  (sentence start only) and re-capitalises; a mid-sentence phrase stays in `hits_after`, which triggers
  the existing one-shot stance_scrub retry and the soft `stance_cadence` finding.
- Drafts: one pattern per language in `live/style_blacklist.json` -> `avoid_patterns` in the compose
  payload + SOFT `template_phrase` finding. Substantive uses ("Continuing weakness in payrolls…") are
  not matched.

Tests: tests/test_direction_drift_oct6.py.
