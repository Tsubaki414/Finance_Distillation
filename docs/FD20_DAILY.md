# fd20: daily drafts for the 20 main accounts (2026-10-07)

The 20 main accounts are rows 1–20 of `FD_accounts_final_v2.xlsx` (主号). They are listed in
`live/fd20_accounts.json`. Nothing here publishes.

## The chain

1. **Ingest:** `scripts/cron/daily_ingest.sh`. EXTRACT and the flash extract run on the official Gemini API.
2. **Route:** each account reads tagged units from its `retrieval_beats`.
   - Both same-language and cross-language material are allowed.
   - Same-language drafts carry no attribution line.
3. **Select:** `scripts/daily_compose.py` picks up to N packets per account (default 2, ceiling 3).
   - It prefers packets that are fresh, inside their shelf life, timely, and not yet used by that account.
   - It also prefers packets that fit the account's angles.
   - Scarce accounts pick first in every round.
4. **Angle:** `live/angles.py` gives each draft one lens.
   - The lens comes from the account's own donor posts: share × lift over the other 19 accounts.
   - At most 2 accounts take the same event, and each takes a different lens.
   - The angle goes into the stance and compose payloads as framing only. It adds no facts.
5. **Format and time:** the habit card supplies `choose_format` (post type and length) and `sample_post_time`. The sampled time becomes the suggested post time.
6. **Compose:** `compose_source` runs stance → compose, Gemini only (`FD_GEMINI_ONLY=1`).
   - There is no Opus fallback.
   - Each draft gets at most 2 stance calls and 3 compose calls.
7. **Cross-account check:** after the whole day is composed, `compose_shapes.batch_findings` and `compose.arbitrate_batch` run.
   - This is soft: a draft that only rephrases the same claim gets HOLD.
8. **Review inbox:** drafts go to `live/compose_inbox.py` and `live/store/compose_inbox/<day>/`.
   - Page: `/compose-inbox` on the 8684 dashboard (`backend/compose_inbox.py`).
   - A static copy is written to `/workspace/x/dashboard/fd20_review_<day>.html`.
   - Review decisions: approve / minor_edit / major_edit / reject. Each needs a reviewer, a reason and the text version.

## Running it

```
FD_DAILY_COMPOSE=1 bash scripts/cron/daily_compose.sh      # also chained at the end of daily_ingest.sh
python scripts/daily_compose.py --select-only               # plan only, no model calls
python scripts/persona_factory.py [--rebuild-cards]         # persona + cluster + habit card + universe
```

### Model settings

| Setting | Effect |
|---|---|
| `FD_GEMINI_MODEL=gemini-3.1-pro-preview` | Switches every Gemini stage. The default is `gemini-3-flash-preview`. |
| `FD_<STAGE>_MODEL` | Switches a single stage. |
| `FD_GEMINI_THINKING=low\|medium\|high` | Sets the thinking level. |

Gemini stages run at temperature 1.0 with thinking set to medium. At temperature 0, Gemini 3 flash looped in thinking until it hit `max_tokens`.

### Budget

- `--budget-usd` (default $4) stops the run from starting new drafts. It counts this run's Gemini spend from the call records.
- `ml/budget` still reserves every call.

## What stays local

These are learned from donor text and are kept out of git (`.gitignore`):

- Habit, language, voice and signature cards
- Donor posts
- `live/store/fd20/universes.json` (sources, angle mix)
