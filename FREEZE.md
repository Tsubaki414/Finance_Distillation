# FREEZE / change log (fd-phase0)

## 2026-10-13 01:50 London — Fiona-approved small changes before the 10-13 recompose
Reason: subrouter + micuapi out of credit (HTTP 402) on the 10-12 23:13 nightly; 0 drafts for Beijing 10-13.
Fiona wants no tokens wasted on drafts that a later gate holds, and depth from the source's own analysis.

- Provider: no code change. `FD_GEMINI_PROVIDER=official` + `GEMINI_API_KEY` (~/.secrets/gemini.env, chmod 600)
  routes every Gemini stage to generativelanguage.googleapis.com (native generateContent, existing route).
  Models unchanged (gemini-3-flash-preview / gemini-3.1-pro-preview, both listed by official /models).
  Cost ledgered at official list rates from live/stage_models.json (flash $0.50/$3.00, 3.1-pro $2/$12 per 1M);
  official calls count toward the cap. Subrouter fallback not wired: it has no credit.
- live/opener_mix.fix_opener: EN ngl/idk/tbh opener stripped at the final opener step (after humanize).
- live/one_per_story.cap_plan (FD_STORY_CAP_SELECT, default on): one story across accounts at SELECTION time
  (URL/source key + day motif keys; today's ready rows lock first); analysis sources ranked before flash/headline
  sources within an account.
- live/depth_check.py (FD_DEPTH_CHECK, default on): compose prompt asks for at least one of the SOURCE's own
  insights (reasoning / comparison / affected / what to watch), never invented; deterministic post-check holds a
  pure headline relay (needs_review). Archive / 回看 rows exempt.
- tests/test_oct13_gates.py; tests/test_compose_recorded.py pins FD_DEPTH_CHECK=0 (recorded prompt).
Backup of the pre-change files: /workspace/x/backups/code_<stamp>/.

## 2026-10-13 07:37 London — official Gemini default for all scheduled runs + pre-draft filters (Fiona approved)
- scripts/cron/provider_env.sh, sourced by daily_ingest.sh / daily_compose.sh / midday_compose.sh / engage_pull.sh
  right after `cd`: loads ~/.config/fd/provider.env (FD_GEMINI_PROVIDER=official, FD_ALLOW_NO_SUBROUTER=1; no
  secrets) and ~/.secrets/gemini.env (GEMINI_API_KEY, chmod 600, never printed). Already-set variables win.
- live/stage_models._official_subrouter_fallback: with provider official and SUBROUTER_API_KEY set, every native
  Gemini stage gets subrouter as a PROVIDER fallback (same model family); a subrouter 402 circuit-breaks it for the
  day (existing fallback_dead). Kill switch FD_OFFICIAL_SUBROUTER_FALLBACK=0.
- live/predraft_filter.py (FD_PREDRAFT master; FD_PRE_FRESH / FD_PRE_LOOKBACK / FD_PRE_FACTS / FD_PRE_BTC_TVN, all
  default on), applied in daily_compose after the story cap and before any model call; BTC then-vs-now cap
  (FD_PRE_BTC_TVN_MAX=1/day across accounts) in live/archive_lookback.run, checked before the X gather.
- Replay of the 10-13 run (42 compose picks + archive rows): 10 compose picks skipped, all 10 had been held
  (0 ready lost), $1.42 of $6.01 compose spend; BTC cap would skip 4 of 5 BTC then-vs-now rows (3 of them ready).
- Pre-existing test failures (unchanged by this commit): test_stage_model_overrides compose_goes_to_second_relay,
  test_research_sources fourpillars, test_fix1012_stage1 archive_humanize line_end, test_x_daily only_x
  (order-dependent / environment; fail identically on a8a1393).
Backup of the pre-change files: /workspace/x/backups/code_0737/.

## 2026-10-13 07:56 London — evergreen freshness exemption, pre-draft evergreen lane gate, daytime caps (Fiona)
- live/fresh_hold.py: 常青 / evergreen rows (archive.variant 'evergreen' or evg-* ids) are exempt from the 48 h
  stale_source hold (they still pass stale_frame). Kill switch FD_FRESH_EVERGREEN_EXEMPT=0 (restores the Oct 12 rule).
  tests/test_fix1012_stage1.py updated to the new rule (old rule asserted behind the kill switch).
- live/predraft_filter.py: FD_PRE_FRESH skips evergreen picks explicitly.
- live/archive_evergreen.candidates: story_dedupe.archive_gate (topic allowlist + story caps, rule-only, no label
  call) runs BEFORE drafting; an off-lane / capped evergreen pick is skipped and handed over. FD_PRE_EVERGREEN_LANE=0.
- Fallback-only behaviour unchanged (FD_ARCHIVE_FALLBACK_ONLY): evergreen still runs only when the account has no
  fresh standalone candidate.
- Caps (~/.config/fd/provider.env, loaded by provider_env.sh): FD_MIDDAY_USD=1.5 per midday run (script default
  also 1 -> 1.5), FD_ENGAGE_FILL_USD=1 per engage fill run (unchanged default). Nightly stays FD_DAILY_COMPOSE_BUDGET_USD
  25 / FD_DAILY_TOTAL_USD 25 (script defaults). Ingest steps of the daytime runs keep their own caps
  (FD_MIDDAY_INGEST_USD 0.4, FD_ENGAGE_PULL_CAP_USD 0.5).
Backup: /workspace/x/backups/code_0756/.

## 2026-10-13 08:40 daytime fill (Fiona 08:02/08:15)
- live/source_licence.json: +4 tier-B manual sources (beincrypto, fxstreet, meta_ai_research, amazon_science) for the morning manual ingest.
- scripts/oneoff_hand_rows_1013.py: one-off, wrote 4 strategy explainers (Fiona-verified in-house backtest numbers) + 3 Morris_LT evergreen translations via compose_inbox.add. Not scheduled.
- Fill compose stopped after round 0: 5/6 held (83% > 60% stop rule); the 1 ready row held on screen (garbled).

## 2026-10-13 08:43-09:20 London — compose-time PREVENTION, life-feel rules, fill fixes (Fiona 08:42 / 08:52)
- live/compose_prevent.py (FD_COMPOSE_PREVENT, default 1; 0 = off): prompt block on every compose — figure whitelist
  extracted from the source/units (only those figures allowed), banned openers (ngl/idk/tbh, 我看, meta openers) with
  2-3 good opener examples per language, the whole "not X but Y" family (不是X而是Y / 原因不在X，是Y / 与其说X不如说Y /
  it's not X, it's Y), no empty step labels, jargon explained on first use, verbatim-only quotes, keep >= 1 source
  insight / no invented opinions, 2-3 key figures only, one genuine human reaction, no NFA/不构成投资建议 except on
  strategy/explainer posts; live/disputed_facts.json (CPI day, KOSPI drop size) -> hedge-or-omit rule.
  Cheap rule checks right after generation; ONE sentence-level repair call ([prevent_repair], own per-draft
  allowance in DraftClient, never a full regen). Post-draft review unchanged as the safety net. Row field compose_prevent.
- live/post_kind.py: life-feel rules — real current events only; no hometown/animals/life story; reaction examples
  no longer teach "ngl"; diary examples carry no invented numbers; BIO_RX also catches pets.
- live/depth_check.py: human kinds (reaction/question/diary/meme/industry_people) exempt; finding carries level=hard
  (rows held as bare "hard: " were this). scripts/daily_compose.py passes post_format.kind to it.
- scripts/daily_compose.py one_per_story: the draft being rewritten (rewrite_of) no longer counts as a prior same-story row.
- tests/conftest.py: FD_COMPOSE_PREVENT=0 for legacy fixture suites; tests/test_compose_prevent.py.
Backup: /workspace/x/backups/code_0843/.

## 2026-10-13 09:30 London — 'policy that moves markets' sources for zh_macro / en_macro (Fiona 09:12)
Config only (live/source_registry.json, live/source_licence.json, live/account_source_universes.json); no code, no compose files.
Backup: /workspace/x/backups/sources_0915/. Polymarket/Kalshi excluded (Fiona).
- Added, analysis (tier B, SECONDARY, topic_match on tariff/trade/sanction/export-control terms, route_accounts zh_macro+en_macro):
  taxfoundation (https://taxfoundation.org/feed/). NOTE: RSS is summary-only, so feeds.fetch_newsletter returns
  radar_only (0 full-text candidates) until a page-fetch adapter exists.
- Added, official fact-check (tier A, context_only, EVENT_ONLY; never content candidates): primary_ustr (ustr.gov/rss.xml),
  primary_mofcom (mofcom.gov.cn index, /syxwfb/art/*.html, body .art-con). primary_fed was already subscribed.
- Added but DISABLED: primary_fedreg_tariff, primary_ofac, primary_bis (Federal Register RSS parses, document pages answer
  'Request Access' to non-browser clients).
- Not added (no parseable feed/listing): PIIE (no RSS, 404s), Global Trade Alert (no RSS), CSIS (rss.xml stale, 2016 items),
  Reuters Markets (HTTP 401).
- 48h freshness and depth rules unchanged.

## 2026-10-13 09:50 London — page fetch, official context capture, proxy-IP check, replacement analysis source (09:16 decision)
Backup: /workspace/x/backups/code_0920/. No compose files touched.
- live/adapters/page_fetch.py (new): bounded article-page fetch for summary-only feeds / HTML listings. Registry opt-in
  `page_fetch` {allowed_hosts, body_selector, listing_url, link_patterns}; HTTPS allow-listed hosts only (redirects
  re-checked), robots.txt honoured, 20 s timeout, login/'Request Access'/JS-challenge pages skipped (never bypassed).
  Ingest still registers only tier A/B sources. live/adapters/feeds.fetch_newsletter uses it for incomplete items,
  supports listing-only rows, and a registry `topic_filter` regex (keeps general feeds on the account angle).
  scripts/run_content_adapters.newsletter_feeds also accepts listing-only rows.
- live/source_recovery.validate_url: the box resolves public hosts to its fixed egress proxy 198.18.0.1 (fake-IP DNS),
  which failed every official fetch (incl. existing primary_fed). Exactly the listed proxy IPs are accepted, only when
  ALL resolved addresses are proxy IPs; any other private/loopback address still fails. FD_EGRESS_PROXY_IPS overrides
  ('' = strict). tests/test_oct13_page_fetch.py.
- scripts/capture_official_context.py (new) + scripts/cron/daily_ingest.sh: nightly official context capture for
  zh_macro / en_macro before the ingest (no model calls, no candidates; non-fatal; FD_OFFICIAL_CONTEXT=0 skips).
  Store: runs/account_sources_v1/store/source_context.sqlite3. Log: /workspace/x/ingest_runs/<day>.official_context.json.
- Sources: taxfoundation gets page_fetch (selector article[id^="post-"]) + tariff/trade topic_filter;
  + atlantic_econographics (Atlantic Council GeoEconomics Center, full-text RSS, tier B, route zh_macro/en_macro).
  account_source_universes: en_macro universe created (09:12 commit had only reached zh_macro);
  tests/test_account_sources expected set updated accordingly.
- Not added: Bruegel (JS challenge page), Brookings / CFR / Tax Policy Center / PIIE (no usable feed or 403/404), AEI (skipped: partisan lean).
