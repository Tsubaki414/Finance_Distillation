# Independent compose lanes (Oct 16, Fiona) - `FD_LANES` (default 1; `FD_LANES=0` = exact old behaviour)

## Why one long compose stalled everything (measured 10-16)
1. `scripts/cron/daily_compose.sh` took ONE flock (`/workspace/x/compose_runs/.daily_compose.lock`) for every
   invocation: nightly, fill rounds, idle guard, midday, engage fill. A second invocation printed "another daily_compose.sh holds the lock: skip".
2. `scripts/cron/engage_pull.sh` and `midday_compose.sh` additionally ran `pgrep -f "scripts/daily_(compose|ingest).py"` and
   exited "skip" while ANY compose / ingest process existed - before their own ingest step, so not even the X pull ran.
3. The Grok Bot routines "FD 白天蹭流量抓取" / "FD 午间新鲜稿" apply the same rule in their prompt (PM_PLAN.md 10-16:
   "SKIPPED - daily_compose already running"): 5 engage pulls (BJT 09:54 11:49 13:45 15:49 17:49) + midday zh (10:38) skipped today.
   The script change alone does not help until the routine prompt stops pre-skipping (see "Routine prompt change").
4. Why the compose ran 4h+ (measured from the call records): 10-16 so far 428 model calls, 105 failed (54 HTTP 524, 47 ReadTimeout at the 300 s
   httpx limit, 4 other) = ~5.8 h of summed failed-call time (4 worker threads in parallel); the subrouter retry loop (4 retries, backoff
   10/30/60/90 s) multiplies it. Per-draft wall time over 10-15/16 (131 drafts): p50 28 s, p90 544 s, p95 1524 s, max 3833 s (64 min for ONE draft).
   Over 10-15/16, 668 calls completed and none took longer than 125 s (p99 121 s), which is why the per-call default is 180 s.
   httpx timeouts are per phase, so a slow-drip body is never cut.

## What changed
| area | change | flag / knob |
|---|---|---|
| locks | one flock per lane: main keeps `.daily_compose.lock`; engage `.lane_engage.lock`; midday `.lane_midday_<zh|en>.lock`; fill `.lane_fill.lock`; mindmap `.lane_mindmap.lock` | `FD_LANE` (else derived from FD_ENGAGE_ONLY / FD_MIDDAY), `FD_LANES=0` |
| skip rules | engage_pull / midday only defer to a running `daily_ingest.py` (content-store writer), no longer to compose | `FD_LANES=0` |
| fill / mindmap lanes | `scripts/lane_fill.py --lane fill|mindmap` (own flock, no main lock) | |
| per-call timeout | hard wall-clock cap per model call (helper thread), default 180 s, shrunk to the account's remaining time | `FD_CALL_TIMEOUT_S` |
| per-account timeout | one account's compose has a total deadline (default 900 s + 30 s grace); after it every model call raises, no retry/fallback; row = `error: account_timeout` | `FD_ACCOUNT_TIMEOUT_S`, `FD_ACCOUNT_GRACE_S` |
| latency log | `[latency] account=<id> stage=<s> seconds=<n> status=<completed|failed:Type>` per call + json rows in `FD_LATENCY_JSONL` (cron sets `/workspace/x/compose_runs/latency_<BJT day>.jsonl`) | |
| inbox files | atomic write (temp + os.replace); add / supersede / review are read-modify-write under a bucketed lock; ids already unique (`compose-<hash incl. time>`; `arc-`, `evg-`, `hand-`, `mm-` from their generators). Rows carry `compose_lane`. Engage rows keep the `compose-` prefix: view ledger + admin decisions reference that id, renaming would break joins | |
| one story per account/day, cross lanes | pick claims (`locks/claims_<day>.json`: `acct:<account>:<source>` and `target:<x-id>` for reply/quote targets, 2 h TTL, only another lane's claim blocks) before any model call; PLUS the inbox write loop re-reads the day's rows inside the day inbox lock before the dup_story check | |
| budget | `ml/budget` ledger was already flock + atomic (reserve/settle). Added day ledger `locks/spend_<day>.json` (all lanes' paid spend) checked against `FD_DAILY_TOTAL_USD` (25) before each paid draft; flat-rate subrouter stays $0 | |
| shared ledgers | anti_repeat history (per persona RMW) locked + atomic; view ledger / archive+mindmap ledgers flock'd append; engagement log merge locked + unique tmp; content_store.add one flock'd batch append + torn-last-line tolerant reader; persona universes / feedback priors atomic; dashboard rebuild+deploy one at a time (`.dashboard.lock`, 25 min wait) | |

## Races found (before this change)
1. Global lock + pgrep = the stall itself (see above).
2. Inbox `add()` used `write_text` (truncate then write): a concurrent reader (`rows()`) could read a half file and skip it -> `drafted_today()` / one-per-story miscounts.
3. `supersede()` / `review()` read-modify-write without lock: lost update between lanes, or between a human review (admin API process) and a compose supersede.
4. One-story-per-account-per-day: the dup_story check used `earlier`, read BEFORE the model calls of the round; two lanes could both write a ready row for the same (account, story). Also the whole-day final sweep rewrote full rows from a stale snapshot (could undo another lane's supersede).
5. Pick selection (`select`) reads `used sources / event caps / tried_sources` at plan time only: two lanes could plan the same (account, source) or two accounts the same reply/quote target. Now claimed.
6. `anti_repeat.record_draft`: read 29 rows, append, rewrite whole file -> concurrent lanes lose rows (test reproduces it without the lock).
7. Appends to ledgers (view ledger, archive/hand/mindmap ledgers) used plain `open('a')`: lines > 4 KB can interleave.
8. `engagement.write_log` read-merge-write with a fixed `.tmp` name: two lanes clobber each other's targets.
9. `ContentStore.add` wrote rows one by one while another process starts and reads `units.jsonl`: a torn last line crashed the reader with JSONDecodeError (new risk once ingest and compose overlap).
10. `persona_factory` (universes.json), `feedback.write`, `build_ops_dashboard.write_if_changed` (fixed `.tmp`): non-atomic / colliding writes now that every lane runs them; Vercel deploy from two lanes at once.
11. Budget: per-run `--budget-usd` is per process; only the shared cumulative `ml/budget` ledger is global. Several lanes could each spend their own cap -> now a day total check.

## Residual (NOT fixed, honest)
- `select()` event caps / per-language event cap and slot-rule counts are computed at plan time; two lanes planning at the same moment can overshoot a cap by up to the number of concurrent lanes (soft caps; the dup_story / claims layers are the hard ones).
- `arbitration_pool` (same-conclusion hold) reads the inbox before the write lock: two lanes can both keep a same-conclusion draft pair (cosmetic, caught by the human review).
- A human `review` landing in the few ms between the final sweep's snapshot and its write can still be overwritten (window is ms; sweep re-reads inside the lock).
- The abandoned helper thread of a timed-out call keeps its HTTP request until httpx's own read timeout (<= 300 s); its result is dropped, but the provider may still bill it.
- `FD_ACCOUNT_TIMEOUT_S` cuts only model calls made through the shared client inside the account's thread; non-model work is not interrupted.
- Two lanes that both call Vercel deploy are serialized, not merged (the second still deploys).
- Routine prompts (outside the repo) still pre-skip - see below.

## Routine prompt change needed (outside this repo)
"FD 白天蹭流量抓取" and "FD 午间新鲜稿" must drop the "if daily_compose is running -> skip" pre-check and just run
`bash scripts/cron/engage_pull.sh` / `midday_compose.sh [zh|en]` (the scripts decide). Evergreen/archive/translation fills:
call with `FD_LANE=fill` (or `python scripts/lane_fill.py --lane fill`) instead of waiting for the main lock; mind-map: `--lane mindmap`.

## Rollback
`FD_LANES=0` in the environment (cron / routine) restores: single global compose lock, pgrep skips, plain writes, no deadlines, no claims, no latency line.
Hard rollback: `git revert` the three `lanes N/3` commits.

## Merge safety (why not merged into fd-phase0 while the 10-16 compose runs)
The running daily_compose.py (pid 601309 child of 419515) lazily imports `live.archive_lookback`, `live.mindmap.fill`, `live.one_per_story`, `live.fresh_hold` ... at its hooks; merging rewrites those files under it (new code + old claims-less parent). Merge after it exits:
`git -C /workspace/fd_new/Finance_Distillation merge --no-ff fd-lanes` (fast-forward is possible: fd-lanes is 3 commits ahead of 57c934e).
