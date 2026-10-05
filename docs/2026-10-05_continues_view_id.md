# Structured `continues_view_id` in the view ledger (2026-10-05)

## Problem
Ledger continuity only lived in `account_view` prose (「延续此前的观察」, "the vulnerability we
previously flagged"). `revises_view_id` covered flips, but a continued call stored no parent pointer,
so every re-read of the same topic appended another "current" view (Oct 5 eve sim: zh_macro had two
near-identical PMI views, both current). `cited_prior_view_ids` was only populated when the model put
prior ids into `supporting_unit_ids` - which the stance prompt forbids - so it was effectively dead.

## Contract
Each recorded call is exactly one of:

| link | field set | who sets it |
|---|---|---|
| continue | `continues_view_id` = prior call carried forward | **deterministic** (`ViewLedger.link_continuity`) |
| revise | `revises_view_id` = prior call being changed | model, validated against supplied `prior_views` |
| fresh | neither | - |

Mutual exclusion is enforced in three places: the linker clears `continues_view_id` whenever
`revises_view_id` is set; `ViewLedger.record` raises if both are present; reject stances carry no
links. `record` also refuses ids that are not recorded views of the account (no invented ids reach
disk). Ledger rows always carry both keys (`null` when unused).

`current()` now treats both continued and revised parents as superseded, so one lasting view is one
chain head; `lineage(view_id)` walks the chain back.

## Design choice: deterministic linking, not model-typed ids
`continues_view_id` is never taken from the model (any model value is dropped in
`_validate_stance_value`). After validation, `stance_step` calls `ledger.link_continuity(value,
prior_views, input_view=view)`:

1. Candidates = the supplied `prior_views` (top-5 `related()` rows), restricted to current chain heads.
2. Match score per candidate (`continue_score`): min-normalised token overlap (EN stems / ZH bigrams,
   same tokenizer as `related()`) of subject vs subject, and of subject+account_view vs the same.
   A candidate is on-topic if subject overlap >= 0.4 **or** text overlap >= 0.3.
3. Direction must equal the new call's direction (`view`, or the adopted input view for a `take`).
   Opposite direction = flip: not linked; the existing `contradicts_prior_view` soft finding stays
   until the model sets `revises_view_id` (recorded as `continuity.unacknowledged_flip_of`).
   Other direction changes (e.g. bearish -> neutral) are left fresh - a revise is the model's call.
4. Best = cited by the model in `cited_prior_view_ids` > higher score > latest call.

Why: the model already only sees prior ids as opaque strings, the Gemini stance output has been
format-unstable (4/9 retries in the Oct 5 sim), and the continue/no-continue decision is fully
determined by data the ledger already has (subject, direction, text). A wrong model-typed id would
silently splice unrelated chains; deterministic linking is reproducible and testable. The model keeps
the one judgment that needs reasoning - *revising* - and can now legitimately cite a prior via the
new optional `cited_prior_view_ids` field (used only as a tie-break hint; unknown ids are dropped).

Applies to `take` as well as `adapt` (a `take` that re-adopts the same call is the most common
near-duplicate). Supplied `stance_output` in `compose_source` (no `stance_step`) is linked right
before `record` when it has no `continuity` marker.

Diagnostics: stance output carries `continuity = {link: continue|revise|fresh|none, source:
ledger_match|model|not_recordable, view_id?, subject_overlap?, text_overlap?, unacknowledged_flip_of?}`.

`ignores_prior_view` no longer fires when `continues_view_id` is set.

## Calibration
Real Oct 5 trading_shortterm R1->R2 (subject wording drifted: "Systematic de-risking vulnerability
into midterm elections" -> "systematic de-risking triggered by steepening index put skew and rising
VIX"): subject 0.40, text 0.32 -> continue. zh_macro PMI day1/day2: 1.0 / 0.98 -> continue.
All cross-topic pairs in that sim score <= 0.05.

## Gaps
- Thresholds are calibrated on one small sim; the trading pair sits right at the subject threshold.
- Cross-language: ZH ledger entries vs EN unit subjects share no tokens, so a ZH persona whose ledger
  subject is Chinese and whose new view subject is English will be `fresh` (same limit as `related()`).
  **Partly addressed 2026-10-06** by a bilingual finance alias layer for high-frequency subjects; see
  `docs/2026-10-06_bilingual_subject_aliases.md`. Long-tail subjects are still language-bound.
- Flips are not auto-linked as revises (by design); an unacknowledged flip stays a soft finding.
- Existing ledger files are not back-filled; old rows simply lack `continues_view_id` (treated as null).
