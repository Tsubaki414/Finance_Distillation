# Hotspots: 母题 pool, per-account decision, reality payload, priors, feedback (Oct 8, Sirius borrow)

Flag `FD_HOTSPOT` (default `1`). `FD_HOTSPOT=0` gives exactly the old selection (checked: the 10-08 select-only plan
with the flag off is identical to the pre-change plan, accounts and pick order). Nothing here publishes.

## Flow (inside `scripts/daily_compose.select`, after the per-account candidate pools are built)

1. **Materials** (`live/hotspot.gather`): every tier A/B source published in the last 36 h in the content store - all
   accounts' sources (flashes, feeds, X intake), grouped by source; X promo openers dropped.
2. **母题 clustering** (`cluster`): deterministic links, then union-find.
   - same URL; same headline event (lead word + numbers); shared news hook;
   - a shared significant number (`$84,000` = `84000美元`, `$25 million` = `2500万美元`; years and round
     1-digit numbers need a rarer entity) plus a shared entity;
   - two shared rare entities; zh headline bigram overlap plus an entity.
   - Entities: known tickers / coins (`live/charts.subjects_in`, so Solana = SOL counts once), `$CASHTAGS`,
     capitalised words outside a stop list, frequent zh names folded to English (罗宾汉 = robinhood).
   - Recaps (早报 / 要闻 / morning briefing, or linked to >= 6 items) may join one 母题 but never bridge two.
3. **One flash merge call a day** (`run_merge`, stage `extract_flash`, relay by default, cost cap $0.30, cached in
   `live/store/hotspot/<day>.merge.json`): sees the core clusters (multi-source or in some account's pool) plus near
   misses (singletons sharing a non-ubiquitous entity / zh headline overlap with them), up to 80; may merge clusters on
   the same story across languages and writes neutral zh / en titles. Unknown ids are ignored, an id is used once, a
   group joins at most 8 clusters. `--select-only` never calls it (uses the cache);
   `--select-only --hotspot-merge` runs or reuses it. Failure = deterministic clusters only.
4. **Heat** (`build_motifs`): `log2(1+publishers) + 0.5*log2(1+sources) + 0.7*log2(1+accounts whose own pool holds a
   member)` + 0.5 x public heat (the `live/heat.py` day cache: Google Trends / 东方财富 / B站 / Reddit, capped at 3,
   never fetched here) + recency `exp(-h/12)`. Pool: `hotspot` when >= 2 publishers (or 1 publisher with public
   heat >= 1 and account reach), else `discovery` (recorded, never written). Type = the posting_habits topic most
   members hit (crypto also from crypto beat tags / crypto terms).
5. **Per-account decision** (`decide`), top 12 hotspot 母题 in heat order:
   - `IGNORE`: no member is in the account's own candidate pool (its retrieval beats, beat gate, own X handles,
     account-scoped sources, not already used by it); or the type's share in the account's own donor topic mix
     (`universes.json` `topic_mix`) < 0.05; or the account has own crypto lanes and no member carries one of them.
   - `HOLD`: on beat but capped - 2 accounts per language per 母题, 1 hotspot per account per day (also across runs:
     a hotspot row already in today's inbox), rewrite targets in `--fill`, or no member timely + prescreen-ok.
   - `WRITE`: otherwise, ranked by topic share x (1 + 0.25 per own top-4 lens the story supports) x the review
     feedback multiplier for that 母题 type.
   - Heat only orders 母题; it never moves an account outside its beat. Accounts with a WRITE skip the old heat
     promotion (their heat is in the 母题 score).
6. **Pick**: WRITE picks go first, inside the account's usual per-run slots (no extra draft). Every source of a
   母题 is one event for the existing per-language event cap, and a 母题 gets a different lens per account in either
   language (`angles.assign` with the lenses already taken). A pick that no longer fits is recorded as HOLD.
7. **Reality payload** (`reality`), attached to the pick and the compose payload (`payload['reality']`):
   - latest price of the 母题's main ticker from the free `live/charts.py` fetchers (Binance 1h / Yahoo daily),
     `as_of` never later than now;
   - the 2-3 newest member sources (<= 24 h, title / publisher / URL / time; X posts only from the account's own
     handles).
   - The lines are appended to the source text the grounding checks read, so a current price taken from them is
     grounded. Rule given to the model: use it only to avoid stating a stale fact as current; do not build the post
     around it, do not name the outlets, copy numbers exactly.
   - Optional X pulse (`FD_HOTSPOT_X=1`, twitter241 `/search-v2`, <= 40 calls/day via
     `live/store/hotspot/<day>.x_calls.jsonl`): a 24 h post count in the sample only, no tweet text. Off by default
     and never in `--select-only`.

## Viral priors (`live/viral_priors.py`, `live/viral_priors.json`, `scripts/build_viral_priors.py`)

Structures, measured on our own donor corpus (aggregates only): `lead_number`, `then_vs_now`, `named_counterparty`,
`question_lead`, `list_format`. Engagement = views (likes if no views) / the donor's own median; lift = median over
donors of median(engagement | structure) / median(engagement | not); donors with >= 40 posts in the language and
>= 8 posts each side. This is an association in donor data, not a causal effect.

| lang | lead_number | then_vs_now | named_counterparty | question_lead | list_format |
|---|---|---|---|---|---|
| en | 1.099 (94 donors) | 1.250 (34) | 1.151 (64) | 1.038 (26) | 1.201 (32) |
| zh | 1.087 (79) | 1.152 (43) | 1.158 (74) | 1.145 (41) | 1.334 (41) |

Use: soft angle ranking only. An angle whose structure the source can carry (e.g. `data_history` / `cycle_position`
-> then_vs_now when the source has a dated comparison) gets `1 + 0.5 x (lift - 1)`, clipped to +-15%, on its share in
the account's own angle mix. It never adds a lens or a fact.

## Feedback loop (`live/feedback.py`, `scripts/feedback_priors.py`)

- /admin actions: approve, **published** (new: "已发布", marked after a human posted it), HOLD, rewrite, edit. The
  console API (`scripts/ops_admin/api/decisions.js`) and `apply_admin_decisions.py` accept `published`; the ops
  dashboard treats it as ready. The API change needs the next `vercel deploy` of the console to take effect.
- Nightly (`scripts/cron/daily_compose.sh`, before compose, never fatal): `feedback_priors.py --pull` pulls the
  newest 3 days, joins decisions with inbox rows and writes `live/store/feedback/priors.json`: per account,
  approve rate by angle id and by 母题 type (`hot:<type>` or `regular`), Beta(1,1) smoothed, with n.
  approve / published = approved, hold / rewrite = not, edit alone not counted.
- Edited text (approve-with-edit, edit, published with text): `live/store/feedback/style_examples/<account>.jsonl`
  (before, after, unified diff). Local only (`live/store` is gitignored); not fed to any prompt yet.
- Next day: `angle_multiplier` / `motif_multiplier` = 1 + (rate - account rate), clipped to +-15%, only when n >= 3.

## Dashboards

`hotspot` on the inbox row (`motif_id`, `title`, zh / en titles, `type`, `heat`, counts, `event_time`) plus
`reality`. Ops dashboard: 「热点」 tag + 母题 title; /admin: 「热点」 tag, 「热点母题：<title> · N 家来源 · M 个号的源里有」
and the 「已发布」 button; review inbox: 【热点】 + title.

## Files

`live/store/hotspot/<day>.json` (materials count, all 母题 with members, decisions per 母题 x account, assignments),
`<day>.merge.json`, run `plan.json` key `hotspot` (top 母题 + assignments).
