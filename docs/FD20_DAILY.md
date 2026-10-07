# fd20: daily drafts for the 20 main accounts (2026-10-07)

The 20 main accounts are rows 1–20 of `FD_accounts_final_v2.xlsx` (主号). They are listed in
`live/fd20_accounts.json`. Nothing here publishes.

## The chain

1. **Ingest:** `scripts/cron/daily_ingest.sh`. EXTRACT, the flash extract and the X-post extract run on the official Gemini API.
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
| `FD_GEMINI_MODEL=gemini-3.1-pro-preview` | Switches every Gemini stage. Compose defaults to `gemini-3.1-pro-preview` (fix26, Oct 7); the other stages default to `gemini-3-flash-preview`. |
| `FD_<STAGE>_MODEL` | Switches a single stage. |
| `FD_GEMINI_THINKING=low\|medium\|high` | Sets the thinking level. |

Gemini stages run at temperature 1.0 with thinking set to medium. At temperature 0, Gemini 3 flash looped in thinking until it hit `max_tokens`.

### Budget

- `--budget-usd` (default $4) stops the run from starting new drafts. It counts this run's Gemini spend from the call records.
- `ml/budget` still reserves every call.

## Donor merge and X sources (Oct 7)

- `live/fd20_donor_merge.json` adds 5 adopted donors per account to its `acct_<id>` cluster.
  - Sources: the Mango Labs team following graph (1 hop), plus a 1-hop gap fill from the followings of strong existing en donors (on-chain, trader, BTC cycle and chart beats).
  - Rules: same language, real individual writers, ≥150 deep-scraped originals, promo_share ≤ 0.25 (LLM per-post read; regex as a floor), at most 3 accounts per donor.
  - Mega accounts (VitalikButerin, saylor, mert, zachxbt, star_okx) are sources only.
- `persona_factory.py` merges them: the base donors keep 50% of the weight (relative weights unchanged) and the adopted donors split the other 50%. It mirrors the result into `live/accounts.json` and rebuilds the merged clusters' cards. Re-runs are idempotent.
- `x_sources` gives each account its own X sources: CORE from the Mango proposals, SECONDARY meme/perp/DeFi/on-chain/chart sources. They are registered in `live/source_registry.json` as account-scoped (`enabled: false` for global intake, `fd20_accounts` lists the users). Individual analysts are licence tier B; media and project accounts are tier C. The fd20 universe lists them as enabled.
- seeds2 pass (same rules): 6 weak donors replaced (single_stock_deepdive_en, zh_us_stocks, zh_longterm_investing), 6 short donors topped up to ≥150 posts instead, logged under `replaced` / `seeds2_note`; up to 6 more X sources per account.

## X daily intake and crypto lanes (Oct 7)

- `live/x_daily.py`, step `x_gather` / `x_extract` of `daily_ingest` (`--only x` runs just this; `--no-x` turns it off).
  - Reads every enabled `x_sources` entry of the fd20 universe. Only tier B handles are fetched; tier C is never fetched.
  - Fetch: RapidAPI twitter241 (`RAPID_X_API_KEY`, uid cached in ingest state, ≤300 requests a run). Handles that fail or come back empty go to one Apify `apidojo~tweet-scraper` run (`APIFY_TOKEN`, ≤300 items, ≤$0.50).
  - Keeps last-24h originals only: no reposts, replies or thread parts; quotes only when ≥140 chars. Drops promo and short posts. At most 4 per handle and 200 a run. Dedupes by post id against state and store, and drops near-duplicates across handles.
  - Extraction uses the cheap batched flash path: ~20 posts per Gemini flash call, X prompt `x_units.EXTRACT`, its own $1.00 ring fence inside the daily cap. No Jev calls.
  - Units keep the handle: `author_name` `@handle`, `source_id` `x_<handle>`, `adapter` `x:<handle>`.
- Beats: `live/jev_front.SUB_BEATS` adds `crypto_meme`, `crypto_perp`, `crypto_defi`, `crypto_airdrop` and `crypto_onchain`. Jev still routes and tags only the 10 `JEV_BEATS`.
  - Sub-beats are keyword tags from `live/beat_rules.py` and need a crypto word.
  - X units get keyword beats, plus the subscribing account's first beat when none of its beats matched.
  - Step `crypto_subbeats` adds sub-beats to any unit tagged `crypto_macro_*`.
- Crypto accounts list their own lanes first in `retrieval_beats` (e.g. `defi_narratives_en`: defi, meme, airdrop, then macro). The universe records them as `lanes`.
- Compose (`candidates`):
  - X units reach only the accounts that subscribe to that handle.
  - Ranking puts own X posts right after timeliness, then packets on the account's own lanes.
  - A same-day re-run counts drafts already in the inbox toward the ceiling of 3.

## Editorial gate and fill (fix26, Oct 7)

Fiona's review of the 26 flash drafts led to these changes:

- **Beat gate** (`live/editorial_style.beat_gate`, applied in `daily_compose.candidates`):
  - Non-crypto accounts never get a packet with 2+ crypto terms (Momo 美股札记 wrote GenLayer).
  - Crypto accounts never get a packet with no crypto content. The exception is the macro crypto accounts (crypto_macro_zh/en, crypto_btc_cycle_zh, btc_cycles_en), which may also take rates / liquidity packets.
  - Generic words (token, wallet) do not count as crypto terms.
- **HARD editorial style** (`live/editorial_style.py`, ported from Sirius `deterministic_editorial_style_failures` + `unauthorized_first_person_experience`). The codes are `editorial_cliche`, `rhetorical_opener`, `overclaim`, `fabricated_experience`, `en_cliche`, `trade_imperative` and `research_tone`.
  - The rule list is in the compose prompt.
  - The codes ride the one structure rewrite. A rewrite may not add a code.
  - A draft that still trips a code is `needs_review` and the inbox row is `held` with `hold_reason`.
- **Event cap:** at most 2 accounts per language per event. Events are matched by source, news hook, or headline lead word plus numbers.
- **Audit + fill:**
  - `scripts/apply_inbox_audit.py <audit.json>` marks rewrite / drop rows `superseded` + `held`. It never touches `review_status`.
  - `daily_compose.py --fill --per-account 2` tops each account up to 2 *ready* drafts. Kept ready drafts seed the event cap, and rewrite rows' sources may be reused.
  - The per-draft reserve is $0.30 on pro.
  - `scripts/apply_inbox_audit.py --recheck <day>` re-runs the style codes on stored bodies after a rule change. Newly tripped ready drafts are held; held drafts whose only hard codes no longer fire become ready. Arbitration and audit holds are never released.
- **Ops page:** `scripts/build_ops_dashboard.py` builds the page. `daily_compose.sh` redeploys it with `vercel deploy --prod --yes` from `/workspace/x/dashboard/ops`; this step is non-fatal, and `FD_OPS_DEPLOY=0` skips it.

## What stays local

These are learned from donor text and are kept out of git (`.gitignore`):

- Habit, language, voice and signature cards
- Donor posts
- `live/store/fd20/universes.json` (sources, angle mix)
