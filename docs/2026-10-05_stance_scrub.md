# 2026-10-05 · Stance scrub + line-1 paraphrase + info_dump rewrite

Follow-on to `docs/2026-10-05_root_cause_compose.md`. The previous fix pinned line 1 to
`thesis_lock = stance.account_view`, which made **dirty stance text** the new leak path:
banned filler in `account_view` taught the draft, and near-verbatim copies of thesis_lock
passed the judgment-first check.

## Fixes

1. **Stance prompt** (`live/stance.py` `STANCE`): `account_view` must be one plain committed
   sentence; no meta-labels; no banned filler families Fiona listed; prefer a falsifiable call.
2. **Deterministic scrub** after the model returns (and on supplied `stance_output` via
   `apply_stance_scrub` in compose): strip meta-label prefixes and known banned spans. Never
   invent facts. If scrub would gut the sentence, revert and keep hits for retry.
3. **One stance repair retry** when hits remain, with `rewrite_note` listing them. Soft
   `stance_cadence` finding if still dirty — compose is never hard-blocked.
4. **Compose paraphrase**: `verbatim_line1` soft finding when line 1 is near-identical to
   thesis_lock. Shares the existing **one** `judgment_repair` retry slot (with `no_judgment` /
   `data_list`) — no retry explosion.
5. **info_dump rewrite**: when `info_dump` / `research_summary` / lingering `data_list` fire on
   JUDGMENT_TYPES or thesis-locked posts, one soft style rewrite (same keep-or-revert pattern as
   anti_repeat). Retain original on guard regression.

## Tests

`tests/test_stance_scrub_oct5.py` — scrub / cadence / verbatim trigger / info_dump retry hook.
Baseline suite still expected green; recorded compose hashes are unchanged only if they never
hit these new repair paths.
