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
