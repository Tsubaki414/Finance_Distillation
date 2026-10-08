# Archive drafts: 回看 (then-vs-now) and 常青 (evergreen)

`live/archive_lookback.py` (gate, material, caps, 回看, run), `live/archive_evergreen.py` (常青), config
`live/archive_lookback.json`, CLI `scripts/archive_lookback.py`. Nothing here publishes.

## What it is

An archive draft fills an account's day with material from last year, taken from the account's own donors and tier-B
X sources.

- **回看 then-vs-now:** what one of those sources said about a year ago, next to today's numbers, with a then-vs-now
  chart. The post quotes only verbatim, names the @handle and the month, and keeps the original URL in
  `archive.original_url`.
- **常青 evergreen:** a high-engagement idea from last year that still holds (a framework, checklist, lesson,
  explainer or thread), re-told as a fresh post in the persona's voice.
  - Material: same-language sources only (no attribution needed, per Fiona).
  - Never copied.
  - No prices, dates or "today" facts.
  - The source URL stays in the row for the reviewer.

## When it runs

- `FD_ARCHIVE`: unset or `1` = on for `enabled_accounts` (`"all"` = the 20 fd20 accounts). `0` = off everywhere.
- Narrowing and variants:
  - `FD_ARCHIVE_ACCOUNTS=a,b` narrows the list.
  - `FD_ARCHIVE_EVERGREEN=0` turns 常青 off; `FD_ARCHIVE_THEN_NOW=0` turns 回看 off.
- Gate:
  - **Fill:** the account's ready non-archive drafts plus the timely packets the normal selection would give it are
    below `target_ready_per_day` (2).
  - **Slow day:** the account has at most 2 ready drafts but fewer than `slow_day_fresh_min` (2) of them come from a
    source published in the last 48 hours. The archive draft is then offered as the 2nd post.
- Limits:
  - At most `per_day` (1) archive draft per account per day, both variants together.
  - One old post is used at most once per account per 30 days, and by one account per day.
  - Ledger: `live/store/archive_lookback/ledger.jsonl`.
- Variant order alternates by day and account position. The other variant is the fallback when the first finds no
  candidate.

## Material and twitter241 caps

- Handles: the account's adopted donors (`live/fd20_donor_merge.json`), then its tier-B CORE / SECONDARY `x_sources`,
  at most 10. Tier C is never fetched.
- Months: the year-ago month(s) of the day, then `months` (2025-02, 2025-09, 2025-10, 2025-11).
- Sources, read in this order:
  1. Local donor timelines in `live/donors/posts/<handle>.jsonl` (`FD_DONOR_POSTS`, outside git). No call.
  2. Every cached page under `FD_ARCHIVE_RAW/raw/<handle>/`. No call.
  3. One twitter241 `/search-v2` **Top** search (engagement-ranked, about 20 posts) per handle and month that has no
     `top_<YYYY-MM>.json` yet.
     - Cached forever and shared by every account that follows the handle.
     - Skipped when the local timeline already has `local_month_enough` posts for that month.
- Caps:
  - `rapid_max_calls_per_day` (40) over all runs of the drafting day. Every call is logged with its `day` in
    `fetch_log.jsonl`.
  - `rapid_max_calls_per_account_day` (4), and an even share of the run's cap.
  - So the cache fills over a few days, and later days are mostly free.
- Engagement = likes + 2 × reposts + 2 × bookmarks + replies + quotes (+ views / 2000).

## Gemini caps

- `model_usd_per_day` ($1) over all runs of the day, from `live/store/archive_lookback/spend.jsonl`. Only calls that
  returned usage count; a refused call is not spend.
- A run stops starting accounts at `compose_reserve_per_draft_usd` below the cap.
- A provider quota error (for example relay 403 `insufficient_user_quota`, or 402) stops the whole run.

## 回看 then-vs-now

- Candidate filter:
  - originals only;
  - no quote posts (their claim leans on a post we do not have);
  - no promo;
  - no personal diary;
  - the account beat gate;
  - a subject with data today (crypto, stocks, FRED / DefiLlama, USD/JPY, USD/CNY, gold, Nikkei, Hang Seng).
- **Claim card** (one flash call per account):
  - Fields: who, when, the claim in one sentence, `claim_type` (prediction / conditional / recommendation /
    observation / opinion / question / personal_update), the condition, whether the claim is about the charted
    subject, and whether the THEN / NOW data `tests_claim`.
  - Only cards with `about_subject` and `tests_claim` that are not personal updates go to compose.
- Compose: one Gemini pro call that picks one candidate and writes the post. The prompt carries the card and the
  fidelity rules.
- Checks (HARD):
  - span grounding;
  - verbatim quotes;
  - look-back framing;
  - stale-as-current;
  - `archive_claim_type`: prediction wording for a claim that is not a prediction;
  - `archive_condition_dropped`;
  - `archive_metric_untested`;
  - **flash fidelity judge** (`archive_misrepresents`): wrong speaker or date, claim type changed, condition
    dropped, quote out of context, view or lesson the author did not express, metric that does not test the claim.
    A judge error is HARD too (`archive_fidelity_unchecked`);
  - editorial style codes.
- Plain-language exemptions: the charted ticker, the source @handle, and words inside a verified quote.
- One targeted rewrite. If anything is still HARD, the draft is held.

## 常青 evergreen

- Rules:
  - originals;
  - same language as the account;
  - long enough;
  - no promo, giveaway, diary or own-book post;
  - the beat gate;
  - an evergreen-shape score (framework / lesson / list markers minus news-of-the-day markers and prices);
  - not used in 30 days, not taken by another account today;
  - not close to the account's 30-day drafts (inbox + persona history, 3-gram overlap ≥ 0.3).
- Ranking: shape score + log engagement + engagement relative to the handle's own posts (at most 2 per handle).
  The top 10 go on.
- Classifier: one flash call returns evergreen?, still true today?, kind, core idea, stale bits and beat fit.
  Only evergreen, still true and fit ≥ 1 go on (top 3).
- Compose: one Gemini pro call that picks one candidate and writes a fresh post.
- Checks (HARD):
  - `evergreen_verbatim`: ZH ≥ 10 identical characters in a row, EN ≥ 7 words;
  - `evergreen_number`: not in the source, or a price, amount or year;
  - `evergreen_dated`: today words, look-back framing, @handle;
  - `evergreen_dup_history`;
  - editorial style codes;
  - flash fidelity judge (`evergreen_misrepresents`): distorted idea, added claim, stale fact as current, copied
    structure.
- One targeted rewrite. If anything is still HARD, the draft is held.

## Inbox and pages

- Rows carry `post_kind: archive_lookback` and an `archive` block with `variant`, the original URL, the post id, the
  text hash and engagement, plus:
  - 回看: the claim card, then / now values and data lines;
  - 常青: the classifier verdict.
- Labels:
  - 回看 rows have `label: 回看` and `post_type: archive_lookback`.
  - 常青 rows have `label: 常青` and `post_type: archive_evergreen`.
  - The ops page, `/admin` and the review inbox show 回看 or 常青 and a link to the original post.
- 常青 drafts are text only. `apply_media` leaves archive rows alone.

## Running it

```
python scripts/archive_lookback.py --day 2026-10-09                                     # all enabled accounts, gated
python scripts/archive_lookback.py --accounts a,b --day 2026-10-09 --fetch-only         # material + ranking, no model
python scripts/archive_lookback.py --day 2026-10-09 --inbox-base /tmp/inbox --rapid-cap 120 --budget-usd 2   # scratch
python scripts/archive_lookback.py --day 2026-10-08 --recheck [--judge]                 # re-check stored 回看 drafts
FD_ARCHIVE=0 ...                                                                        # off
```

`--recheck` without `--judge` makes no model call. It keeps a stored judge verdict, so a checker fix never releases a
misrepresentation. With `--judge`, it builds the claim card and re-runs the judge (flash).

`scripts/daily_compose.py` calls `archive_lookback.fill_gaps(day, accounts=...)` at the end of a run.
