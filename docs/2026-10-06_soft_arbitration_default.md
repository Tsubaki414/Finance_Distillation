# Soft claim arbitration on by default (P1-2, 2026-10-06)

- `live.compose.arbitrate_batch(results, mode=None)` now resolves the mode as: explicit `mode` >
  env `FD_ARBITRATION` > **`soft`** (default). Soft = same-day same-conclusion drafts from different
  accounts: best lane keeps WRITE, the others get `arbitration.status=HOLD`, a soft
  `cross_persona_claim_duplicate` finding and `status=held`. Text is never deleted; opposite
  directions never collide.
- `live.compose_batch.compose_batch(jobs, client, ...)` is the batch/daily compose entry point: it
  composes every job (an error becomes a `status=error` row instead of aborting the batch) and always
  finishes with `arbitrate_batch`. `scripts/demo_matrix_compose.py` uses the same default.

## Turning it off
- One run: `compose_batch(..., arbitration='off')` or `arbitrate_batch(results, mode='off')`.
- Whole process: `FD_ARBITRATION=off` (also accepts `0/false/no/none`).
- Off returns the drafts unchanged, each with `arbitration = {'status': 'OFF', 'mode': 'off'}` so a
  reviewer can tell "not arbitrated" from "WRITE". Unknown values raise (no silent fallback).
- Matrix demo: `FD_ARBITRATION=off python scripts/demo_matrix_compose.py --live ...` (the labelled
  synthetic HOLD example stays explicitly soft; it only illustrates the mechanism).
- Legacy `scripts/run_content_batch.py --account X` is a single-account run, so there is no
  cross-persona pair to arbitrate there; multi-account daily runs should go through `compose_batch`.

## ZH/EN matrix selection (v3, same day)
`demo_matrix_compose.select_groups` no longer prefers a shared ZH+EN source (v2 made both ZH slots
HOLD). EN takes its best balanced packet (view + fact); ZH takes its best balanced packet from a
different source, ZH-native first (`own_zh_native` / `own_different_source`). Only without any such
packet does ZH share EN's source, keeping the views EN does not carry (`shared_differentiated`);
with no different view the slice is kept and marked `shared_same_angle`, and soft arbitration HOLDs
the genuine duplicate. The mode is recorded per draft as `result['selection']`.
