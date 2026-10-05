# 2026-10-05 — pack augment + EN no_judgment harden

## Daily ingest
- Run OK with ACCOUNT_RELAY_* (~$7.89/$8). Report: operator `ingest_runs/20261005.json`.
- `options_flow` included in `live/daily_ingest.py` default fetchers.
- Cron exports `FD_PACK_AUGMENT=1`.

## Pack balance (daily path)
- `compose.augment_non_fact_units`: pure-fact packs pull ≤2 persona-tagged non-facts from the store.
- Enabled only via `compose_source(..., pack_augment=True)` or `FD_PACK_AUGMENT=1` (default off for offline/tests).
- Horizon-compatible filter; stance-reject of an augmented view reverts to the source pack.
- `choose` / `pick_units` prefer horizon-compatible view primaries.

## EN no_judgment
- Stance-field matching retained; without stance, declarative thesis / imperative / evaluative openings pass.
- Markers include dovish/hawkish/premature. Bare data and bare questions still fail.

## Tests
- Suite: 22 baseline failures unchanged (`run_suite`).
