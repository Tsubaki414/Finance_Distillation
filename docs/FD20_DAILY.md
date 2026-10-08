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

- `--budget-usd` (default $8 since Oct 8; was $4) stops the run from starting new drafts. It counts this run's Gemini spend from the call records.
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
  - Live review sync: the ops page (`/`) and `/admin` both read `/api/decisions?day=<shown day>` on load, every 60 s, on the 「刷新」 button and after each action (the page data itself — new days, rebuilt drafts — is re-read every 5 min and on 「刷新」 with `cache: 'no-store'`). On `/`, HOLD / 要求重写 drafts drop out of the default 可发 filter, edited text replaces the draft text (copy buttons and the CSV button copy the edited text) and approved / edited drafts are tagged. Both pages open on the newest Beijing day that has drafts; a `#<day>` hash is only kept when someone picks an older day.
  - 「已发」 is shared: ticking it on `/` POSTs `published`, unticking POSTs `clear` when the decision is only 已发 and `unpublish` otherwise (an admin's edit / approve stays). Decisions store the flag as `published` (bool) plus `before_publish` (what `unpublish` restores); the stored `action` stays in approve|published|hold|rewrite|edit|clear so `apply_admin_decisions.py` / `feedback.py` read it unchanged, and old blobs (action `published`, no flag) still count as published. Ticks made while the API is down wait in localStorage (`fdops:pending:<day>`) and are retried; old per-browser ticks (`fdops:posted:<id>`) are pushed to the shared flag once. The rule lives once in the `<shared>` block of `scripts/ops_admin/api/decisions.js` and is inlined into both pages.

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

- Since 2026-10-08 the image path is `live/media_real.py` (per-account donor-like styles, donor image rate, public-page captures with rendered fallback); see `docs/MEDIA_REAL.md`. `FD_MEDIA_V2=0` restores the Oct 7 charts below.
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

## Archive drafts: 回看 then-vs-now and 常青 evergreen (Oct 8, all 20 accounts)

- `FD_ARCHIVE` (default on) runs for all 20 accounts (`live/archive_lookback.json` `enabled_accounts: "all"`).
  At most 1 archive draft per account per day: to fill an account with < 2 ready drafts, or as the 2nd post on a slow
  day (fewer than 2 ready drafts from a source of the last 48 hours).
- Two variants, alternating by day and account, the other one as fallback:
  - 回看: a post by the account's own source from about a year ago next to today's data, with a then-vs-now chart.
    A flash claim card (who, when, claim type) must show the data tests the claim, and a flash fidelity judge
    holds any misrepresentation.
  - 常青: a high-engagement, still-true idea (framework / checklist / lesson / explainer) from last year's same-language
    posts of the account's sources, re-told in the persona's voice with no copying and no stale numbers.
- Caps: <= 40 twitter241 calls a day (one Top search per handle and month, cached forever, shared across accounts),
  <= $1 Gemini a day for this path.
- Rollback: `FD_ARCHIVE=0` (off), `FD_ARCHIVE_ACCOUNTS=<ids>` (narrow, e.g. the 3 pilot ids),
  `FD_ARCHIVE_EVERGREEN=0` / `FD_ARCHIVE_THEN_NOW=0` (one variant off).
- See `docs/ARCHIVE_LOOKBACK.md`.

## Hotspots (Oct 8, Sirius borrow; `FD_HOTSPOT`, default 1)

- After the candidate pools are built, the day's materials across all accounts' sources are clustered into 母题
  (deterministic links + one cached flash merge call a day, <= $0.30), scored by cross-source breadth, public heat and
  recency, and each account marks the top 母题 WRITE / HOLD / IGNORE by its own beat, topic spread and lanes.
- Max 1 hotspot draft per account per day (inside its usual slots), 2 accounts per language per 母题, a different
  lens per account. WRITE picks carry a reality payload (latest price + newest same-story sources) into compose.
- Soft priors: viral structure priors from our donor data and the /admin review feedback (incl. the new 「已发布」
  action) re-rank lenses / 母题 by at most +-15%. 「热点」 tag on the ops page, /admin and the review inbox.
- Feedback v2 (PM item 5): the 已发 flag survives the pull; outcomes published as-is / after edit / approved not
  posted / unpicked / held / rejected; priors need >= 6 scored drafts per account and >= 3 per key; stats.json +
  the /admin 「反馈闭环」 panel (publish / edit / hold rates per account, angle, 母题 type, post_kind, format, media).
  `FD_FEEDBACK_V2=0` restores v1. See `docs/HOTSPOT.md`.
- `FD_HOTSPOT=0` restores the old selection exactly. See `docs/HOTSPOT.md`.

## Topic diversity and X breadth (Oct 8)

- Each account's picks come from its own X sources first, then donor-adjacent packets, then shared news; the two picks
  of a day take different themes when the pool allows; one story goes to at most 2 accounts per language and 3 in all.
  Hotspot WRITE needs an own / donor-adjacent member. `FD_TOPIC_DIV=0` restores the previous selection exactly.
- 70 tier-B X sources from the Sirius list, mapped to accounts by donor theme mix + donor mentions
  (`live/x_breadth.json`), fetched by batched search, <= 20 twitter241 calls a day (`FD_X_BREADTH=0` turns it off).
- Daily compose budget default $8. See `docs/TOPIC_DIVERSITY.md`.
- Oct 8 pm-voice: the Sirius list had 0 handles for market_data_charts, so its 12 breadth handles come from its own
  donors' @-mentions (`scripts/x_breadth.py mentions --account market_data_charts`, then `evaluate --lookup
  --candidates ...` and `assign --accounts market_data_charts --merge`, which adds picks and keeps every other
  handle). Same `usable` / org / score rules; `live/x_breadth.json` "merged" records the addition.
- Oct 8 donor review (zh_us_stocks, single_stock_deepdive_en, investing_philosophy, zh_longterm_investing): off-topic
  donors removed from `live/donors/roster.json` + `live/fd20_donor_merge.json` ("removed" lists handle, account and
  reason); weights re-derived by `scripts/persona_factory.py`. Voice / signature cards stay local (not in git).

## Quality / reliability (Oct 8 PM P1, `fd-pm-quality`)

- **Own X posts with half a pack** (`live/x_support.py`). A view-only own X post gets a real support fact attached:
  a same-story public source (deterministic 母题 links, or a known coin / stock / $CASHTAG the view's own subject
  names and the fact states) within 48h, else the latest price of the ticker the view names (free chart fetchers,
  known symbols only). The fact keeps its own source; its span joins the evidence packet (grounding), the inbox row
  carries `support` + `support_citations`, the review page shows 「补充事实」. A fact-only own X post with a money /
  percent / multiple number becomes a `data_take` packet. Both rank after balanced own X posts.
  `FD_X_SUPPORT=0` / `FD_X_DATA=0` / `FD_X_SUPPORT_PRICE=0` turn them off.
- **Selection prechecks** (`FD_PRECHECK`, default 1): packets compose would refuse before any model call are not
  planned - a source without a creditable name in the account's language, and judgment packets without a structured
  view whose horizon fits the persona (10-08: 39 of 40 not_suitable plans were these).
- **Fill rounds** (`FD_FILL_ROUNDS`, default 3): after the first pass, accounts short of `--per-account` ready drafts
  get the next untried candidates until they have them or candidates / budget / quota run out. Sources an account
  already composed today (not_suitable, held, error - not budget / quota stops) are skipped
  (`FD_FILL_SKIP_TRIED=0` turns that off). `fill_status.json` in the last run dir says why each account stopped.
- **Errors**: evidence spans with outer whitespace / blank lines no longer raise StopIteration; a stance contract
  error gets one targeted retry; a relay transport failure (ReadTimeout ...) is retried once after 5 s; the relay's
  balance error (用户额度不足) and the official 402 stop new drafts like a quota error.
- **Holds**: arbitration only compares accounts of one language (`FD_ARB_SAME_LANG=0` = cross-language as before) and
  only drafts that can ship (a needs_review draft no longer takes the lane). Chain / token names in capitals
  (TRON, STG, HYPE ...) are not `jargon_unexplained`.
- **Hotspots**: a lane account also takes a 母题 outside its lanes when its type has topic share >= 0.2; a 母题 made
  only of X posts needs >= 3 distinct authors for the hotspot pool.

## 36 accounts: 6 spares + 10 new (Oct 8)

Yams: Mango has 36 accounts. The 6 spare accounts are now in use, and 10 new accounts were added; Fiona asked for
meme and airdrop accounts first. Nothing publishes automatically.

- **Roster**: `live/fd_accounts.py` is the only reader.
  - `live/fd20_accounts.json`: the 20 mains (file unchanged).
  - `live/fd_accounts_extra.json`: the 6 spares, nos. 21–26, status `spare_active`, gated by `FD_ACCOUNTS_EXTRA`.
  - `live/fd_accounts_new.json`: the 10 new accounts, nos. 27–36, status `new`, gated by `FD_ACCOUNTS_NEW`.
  - Both gates default to 1. Setting one to 0 removes that group from daily_compose, archive look-back, the X intake
    (`live/x_daily.subscriptions` skips universes tagged with that group), persona_factory, the ops page and /admin,
    and claim arbitration. A caller that passes its own accounts file still gets exactly that file.
- **Rows**: same fields as fd20 rows, plus:
  - `donors` and `x_sources` (CORE = the donors; tier B registered in `live/source_licence.json` by persona_factory).
  - New rows only: `positioning`, `does_not_write`, `risk_rules`, `donor_evidence` (twitter241 check on 10-08:
    followers, last post, originals scraped, promo share; aggregates only), `source_needs` (wired / not wired), and
    `lane_first`.
- **persona_factory**:
  - Builds clusters from row donors.
  - Adds new-account donors to the roster as voice donors; existing roster verdicts are kept, which is why @0xdahua
    (promo_heavy) and @0xScottBTC (radar) were dropped as donors.
  - Writes persona files, emotion tiers, `--no-llm` voice cards, habit / language cards and universes (with
    group / status).
- **Donor post tags** for the 55 new donors use the deterministic rule fallback of `jev_front.tag_posts`
  (`jev_fallback: true`). Retag with `scripts/donor_style_stats.py --jev --only-fallback live/donors/tags` once
  TypeSafe is in budget; then rebuild cards with `persona_factory.py --rebuild-cards --accounts ...`.
- **Media**: `scripts/build_media_profiles.py --only-missing` added the 16 accounts and left the 20 untouched.
  - image_rate comes from the account's own donors.
  - chart share and styles are the family's, because there is no classified image sample of the new donors yet.
- **New lanes**:
  - `crypto_prediction` (needs Polymarket / Kalshi / 预测市场).
  - `crypto_stable_yield` (needs a stablecoin word and a yield word).
  - `crypto_ecosystem_sol_base` (Oct 8 b; an ecosystem word plus Solana / Base by name: `solana`, `$SOL`, `@base`,
    `on Base`, `Base app / chain / TVL ...`; "base" alone does not count).
  - Tagging: `live/beat_rules.lane_tags` runs on every unit in the `crypto_subbeats` ingest step, so older units are
    included. `topic_div` gained the theme `c_prediction`.
  - The `ipo` keyword lane and topic theme were removed with zh_hk_ipo (Oct 8 b); `KEYWORD_LANES` stays as an empty
    mechanism.
- **Structured lane sources**: public, no key / login, one GET per ingest, deterministic units.
  - `polymarket_markets` (Gamma API; sports and tweet-count markets left out).
  - `defillama_yields` (single-asset stablecoin pools > $100m TVL).
  - All are tier B and routed (`route_accounts`) only to the matching new accounts. They are wired in
    `live/daily_ingest.default_fetchers`, which skips them when `FD_ACCOUNTS_NEW=0`.
- **Selection**:
  - `lane_first` accounts move own-X / own-lane packets ahead of general news (`FD_LANE_FIRST=0` turns it off).
  - Fact-only packets of a source routed to the account become data_take packets (`FD_LANE_DATA=0` turns it off).
  - `editorial_style.beat_gate`: Polymarket / Kalshi / 预测市场 count as crypto content, and a row with
    `ai_crossover` (Tango 探戈) also takes AI packets.
- **Risk rules** (`live/risk_rules.py`): HARD in qa_levels, run in compose and both archive variants, for all
  accounts. They HOLD on:
  - contract addresses (EVM / base58 / `CA:`);
  - guaranteed-return wording (稳赚 / 保本 / 必涨 / guaranteed / risk-free / next 100x; negated mentions pass);
  - a call to act next to presale / whitelist / wallet-approval / send-funds wording;
  - referral or invite codes.
- **No 31 replaced (Oct 8 b, Fiona)**: 打新阿梨 (zh_hk_ipo) is dropped together with the `ipo` lane, the Nasdaq IPO
  calendar adapter, its persona / cluster / roster donors / licence entries / media profile. In its place
  `sol_base_alpha_en` (Dax 🧃, en, mid): Solana / Base ecosystem launches, app usage, chain metrics, builder
  and funding news, Solana vs Base flows; memes and points only as ecosystem context (tully and tilda own
  those). Donors SolanaSensei, SolanaHub_, Tanaka_L2, BaseHubHB, baseposting (CORE, tier B); @solana / @base /
  @buildonbase / @SolanaFloor are SECONDARY but tier C (project / media accounts are topic leads only, as in fd20).
  No structured chain-metrics source: DefiLlama's terms forbid commercial exploitation / republishing without
  written consent, Token Terminal / Artemis / Dune need keys.
- **Check**: `python scripts/check_fd_accounts.py [--accounts a,b] [--day D] [--json out]`, offline, no model calls.
  It reports config, donor topic spread, per-lane units, the post-gate packet pool, and one select over the whole
  roster with ops-page post times.
