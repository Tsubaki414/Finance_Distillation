# 回看 (archive / look-back) post type (Oct 8 pilot)

`live/archive_lookback.py`, config `live/archive_lookback.json`, CLI `scripts/archive_lookback.py`. Nothing here publishes.

## What it is

The 回看 post type fills an account's day when its fresh publishable material is thin. Each draft:

- looks back at a post by one of the account's own sources from about a year ago (Feb 2025 first, then the same
  calendar window one year before the day);
- says what was said then, quoting only verbatim from the original post, and keeps the original URL in
  `archive.original_url`;
- compares it with today's numbers and carries a then-vs-now chart.

## When it runs

- `FD_ARCHIVE`: unset or `1` means on, but only for `enabled_accounts` in the config (the pilot: `crypto_altcoin_zh`,
  `crypto_macro_en`, `zh_longterm_investing`). `0` turns it off everywhere.
- Gap gate: the account's ready non-回看 drafts for the day plus the timely packets the normal selection would give it
  must stay below `target_ready_per_day` (2).
  - The CLI simulates `daily_compose.select` for the day. It makes no model calls.
  - The `daily_compose.py` hook runs after the day's drafts are in and uses the inbox count only.
- At most 1 回看 draft per account per day.
- The same old event is used at most once per account per 30 days.
  - Ledger: `live/store/archive_lookback/ledger.jsonl` (ignored by git).
  - Keys: the post id, plus handle + subject + date.

## Material

- Handles: the account's adopted donors (`live/fd20_donor_merge.json`), then its tier-B CORE and SECONDARY
  `x_sources`. At most 10 per account. Tier C is never fetched.
- Fetch: twitter241 `/search-v2` with `from:<handle> since: until:`, 20 posts a call.
  - Windows: `feb2025` (whole month, which returns the late-Feb tail), `feb2025_early` (Feb 1–14) and `year_ago`
    (day − 365 ± 10 days, ranked after Feb).
  - Raw pages are cached in `/workspace/x/archive_lookback/raw/` (`FD_ARCHIVE_RAW`, outside git).
  - Every call is logged to `live/store/archive_lookback/fetch_log.jsonl`.
  - Caps: `rapid_max_calls` 150 per run.
- Candidates must pass all of these:
  - originals only;
  - no promo;
  - the account beat gate (`editorial_style.beat_gate`);
  - a subject with data today: a `charts.CRYPTO` / `charts.STOCKS` symbol, a FRED / DefiLlama series, or one of
    USD/JPY, USD/CNY, gold, Nikkei, Hang Seng. Unknown cashtags do not count.
- Ranking puts Feb first. Personal trading-diary posts and crypto subjects on non-crypto accounts rank lower.
  At most 2 per handle; up to 6 go to the model.

## Today's numbers and chart

- Crypto: `charts.fetch_crypto` (Binance, 1000 daily bars).
- FRED / DefiLlama: `charts.fetch_series`.
- Stocks, FX and indexes: Yahoo 2-year daily range through `charts._get`. `charts.fetch_stock` cannot be used here:
  it reaches back only one year, and its weekly path sends `interval=1w`, which Yahoo rejects with 400.
- Data lines are dated:
  - `THEN` (close on the post date);
  - `NOW` (latest, with the fetch time);
  - `CHANGE` (signed and unsigned).
- These lines are the only source the draft may take today's numbers from.
- The chart is a line from 30 days before the post to today, with both points marked. It is stored as media
  kind `archive_chart`, so `scripts/refresh_charts.py` leaves this fixed image alone.

## Writing and checks

- One Gemini compose call (`FD_GEMINI_PROVIDER`, relay by default; `gemini-3.1-pro-preview`, explicit non-library
  User-Agent). It picks one candidate (or NONE) and writes the post. Run cap: `compose_budget_usd` $1.50.
- Checks, HARD unless noted:
  - span grounding: numbers / quotes vs the original post + data lines (@handles masked);
  - `archive_quote_not_verbatim`: a quote not copied character for character, or a translated quote;
  - `archive_framing`: the first line has no 回看｜ / "Look back:", no 2025 date, or no today / as-of marker;
  - `archive_stale_as_current`: the old value written as today's;
  - editorial style codes: clichés, fabricated first person, trade imperatives, plain language.
- Plain-language exemptions, only for 回看: the charted subject's own ticker, and words inside a verified verbatim
  quote.
- One targeted rewrite names each failure. Still hard afterwards = HOLD (`hold_reason: hard: ...`).
- `--recheck` re-runs the checks on stored bodies after a checker fix. It makes no model call and leaves the text
  unchanged. Every recheck is recorded in the row's `rechecks`.

## Inbox and pages

- Rows carry `post_kind: archive_lookback`, `label: 回看`, `post_type: archive_lookback` and an `archive` block (original URL,
  post id, text hash, quotes, then/now, data lines, event keys).
- The ops dashboard and `/admin` show a 回看 tag plus a 回看原帖 link. The review inbox page prefixes 【回看】.

## Running it

```
python scripts/archive_lookback.py --accounts crypto_altcoin_zh,crypto_macro_en,zh_longterm_investing --day 2026-10-08
python scripts/archive_lookback.py --day 2026-10-08 --fetch-only   # fetch + rank, no model, nothing written
python scripts/archive_lookback.py --day 2026-10-08 --recheck      # re-run checks on stored 回看 drafts
FD_ARCHIVE=0 ...                                                   # off
```

`scripts/daily_compose.py` calls `archive_lookback.fill_gaps(day, accounts=...)` at the end of a run (the 回看 hook block).
