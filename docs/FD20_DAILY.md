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
FD_HEAT=0 python scripts/daily_compose.py --select-only --now 2026-10-07T23:13+01:00   # simulated clock -> day 2026-10-08
python scripts/persona_factory.py [--rebuild-cards]         # persona + cluster + habit card + universe
```

### Schedule and drafting day (Oct 7)

- The drafting day is the **Beijing calendar date** (Asia/Shanghai): inbox `<day>` dirs, run dirs, CSVs, `media/<day>`,
  review page, the dashboard date selector and its 08:00–22:59 北京时间 slots. `daily_compose.py --day` defaults to it.
- Trigger `daily_ingest.sh` at **23:13 Europe/London**: 06:13 Beijing in BST, 07:13 after 25 Oct 2026. Drafts for
  Beijing day D are up before D's 08:00 slots. Cron logs keep the London run date (`<London date>.cron.log`).
- Ingest windows are now-relative (X 24h, flashes 26h), so the 23:13 London run covers the whole US session of that
  London day. The ingest summary `/workspace/x/ingest_runs/<YYYYMMDD>.json` is named by the Beijing date too.
- Selection reference = the run time for a run on or just before the drafting day (no future as-of); 08:00 Beijing
  of `--day` for a backfill of an older day. `--now <ISO+offset>` simulates the clock (use with `--select-only`;
  `FD_HEAT=0` keeps it free of the heat fetch).
- Days before 2026-10-08 were London dates of the 05:13 London run, which is the same calendar date in Beijing, so
  2026-10-07 and older data read unchanged.

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
  - `--rewrite-notes notes.json` (`{draft_id: note}`, with `--fill`): those held drafts are rewritten from the same source with the note in the compose payload (`editor_note`). Audit-superseded rewrite drafts use their audit reason as the note by default. New rows carry `rewrite_of`. The event cap and own-account duplicate check still apply.
  - X posts that open as a thank-you / congrats / welcome / announcement are skipped as material (`X_PROMO_OPENER`).
  - `scripts/apply_inbox_audit.py --recheck <day>` re-runs the style codes on stored bodies after a rule change. Newly tripped ready drafts are held; held drafts whose only hard codes no longer fire become ready. Arbitration and audit holds are never released.
- **Ops page:** `scripts/build_ops_dashboard.py` builds the page. `daily_compose.sh` redeploys it with `vercel deploy --prod --yes` from `/workspace/x/dashboard/ops`; this step is non-fatal, and `FD_OPS_DEPLOY=0` skips it.

## What stays local

These are learned from donor text and are kept out of git (`.gitignore`):

- Habit, language, voice and signature cards
- Donor posts
- `live/store/fd20/universes.json` (sources, angle mix)

## Gemini provider switch (Oct 7 afternoon)

- `FD_GEMINI_PROVIDER=relay|official`, default `relay`. It moves every Gemini stage (compose, stance, extract, extract_flash, view_enrich).
  - `relay`: micuapi OpenAI-compatible `/v1/chat/completions`, key env `GEMINI_RELAY_API_KEY`. The thinking level goes as `reasoning_effort`.
  - `official`: native `generateContent` with `GEMINI_API_KEY`. Official prepaid credits ran out (402) at about 11:45 on Oct 7.
- Model names, rates, max_tokens and thinking level are the same on both. No fallback either way: a failure raises.
- Spend is a local estimate at Google list prices, not the relay invoice.

## Hard rewrite, span grounding and supersede (Oct 7, Sirius borrow items 2 + 4)

- Span grounding (`live/span_grounding.py`): every factual sentence of the body is mapped to a source span (unit
  spans first, then the source text). A number no span holds (rounding to the written precision is fine) or a
  same-language quote that is not verbatim is HARD (`ungrounded_number`, `ungrounded_quote`). An unknown
  ticker / Latin-script name (`ungrounded_entity`) or a reporting sentence with no matching span
  (`ungrounded_claim`) is a warning. Dates, years, quarters and bare counts up to 10 are skipped; CJK names are
  not checked. The per-sentence map is stored on the draft as `span_grounding`.
- One targeted rewrite: HARD findings on the kept draft (style blocks, grounding, position / trade / quote codes)
  get exactly one compose rewrite whose note names each failure and its detail (`hard_repair` on the draft). Still
  hard afterwards = HOLD (`hold_reason: hard: ...`). The frame / licence codes are not rewritten. HARD style codes no
  longer ride the soft structure regen, so nothing is rewritten twice for the same hard code.
- Model / API errors stay separate: transport retries live in `compose._ask`; the hard rewrite has its own per-draft
  allowance in `daily_compose.DraftClient` (2 calls), so polish rewrites cannot use it up. A rewrite that never came back
  is held as `model_error: ...`, not a content verdict, and a later `--fill` can retry.
- Supersede: a rerun or rewrite of the same account + source marks the earlier inbox draft `superseded`
  (`superseded_by`, `superseded_reason` rerun / rewrite). Nothing is deleted. A held rerun never replaces a ready
  draft, and drafts a human has already reviewed are left alone.
- Quote-tweets, reposts, replies and images: design only, see `docs/post_types_media.md`.

## Chart refresh (Oct 7)

- Level lines: `charts.draft_levels` draws a price the draft names (dashed line, small boxed label) only when it has a
  price cue (`$`, 美元/点/USD after it, or support / resistance / 支撑 / 突破 / 关口 … before it), is not an amount,
  %, count, duration, date or year (亿, million, 倍, 小时, 枚, 500 BTC …), and sits within the plotted range ±15% and
  −40% / +60% of the last close.
- `scripts/refresh_charts.py`: today's + tomorrow's (Beijing inbox days) ready drafts. Candlesticks are refetched
  every run (cache bypassed); data charts at most every 6 h. An image is replaced only when its `data_sha` (plotted
  rows + levels, not the fetch stamp) changed; that sets `refreshed_at`, shown on both pages as
  「图更新于 北京时间 HH:MM」, and the image URL gets `?v=<sha>`. Pages are rebuilt; `vercel deploy --prod --yes` runs
  only when an image changed (or an earlier change is still `deploy_pending`).
- Schedule: `scripts/cron/refresh_charts.sh` (log `/workspace/x/chart_refresh/<day>.log`, `flock` on
  `refresh_charts.lock`), crontab `17 * * * *`; the wrapper exits outside 08:00–23:59 Beijing time.
  This box had no cron at all before Oct 7 (daily_ingest / daily_compose were never on a crontab here); cron was
  installed and started for this line only. A container restart needs `sudo service cron start`.

## 2026-10-07: research sources Four Pillars + Delphi Digital

- **Four Pillars** (tier B: reference and paraphrase, short quotes with attribution, no full-text republishing).
  - X `@FourPillarsFP`: `x_sources` SECONDARY of crypto_research_en / crypto_research_zh / defi_narratives_en /
    crypto_thesis_en in `live/fd20_donor_merge.json` (and the local universes), fetched daily by `live/x_daily.py`
    (twitter241), licence `x_FourPillarsFP`.
  - Articles: `live/adapters/fourpillars.py`, daily_ingest channel `research:fourpillars_research`.
    research.4pillars.io answers non-browser clients with a Vercel checkpoint (429) that we do not work around;
    the official newsletter RSS (`fourpillarsfp.substack.com/feed`) lists each research article (title, link,
    bullet key claims) in its "Four Pillars Weekly" section. One dated source per article (title, URL, summary,
    key claims), last 30 days, articles with no bullets (chart-only data posts) skipped.
  - Routing: registry `route_accounts` / `route_beats` (`live/source_routes.py`): units are tagged `crypto_defi`
    without Jev routing, and `daily_compose.candidates()` offers them only to the four accounts above.
- **Delphi Digital** (members-only, `inspiration_only`, adapter `browser_digest`): no scraping / cookies / CDP; a
  browser routine writes `live/store/delphi_digest/<day>.json`. Schema, validation and the licence gate:
  `docs/DELPHI_DIGEST.md`.

## 回看 look-back post type (Oct 8 pilot)

- Pilot accounts: `crypto_altcoin_zh`, `crypto_macro_en` and `zh_longterm_investing` (`FD_ARCHIVE`, `live/archive_lookback.json`).
- When an account is short of fresh ready drafts, it gets one draft that compares a post by its own source from about a year ago (Feb 2025 first) with today's data, plus a then-vs-now chart.
- See `docs/ARCHIVE_LOOKBACK.md`.
