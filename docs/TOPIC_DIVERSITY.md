# Topic diversity and X source breadth (Oct 8)

Fiona on the 10-08 batch: 40 picks for 20 accounts came from a handful of shared news items (4x Polygon / TRON,
4x Glassnode "A Rally Running Light", 4x Wells Fargo / Kraken, 4x Robinhood $25M, 4x "Down but not out"), while each
account's donors post on many different stories every day. An account's day should follow its own donors and its
own sources. Nothing here publishes.

## Selection (`FD_TOPIC_DIV`, default 1; `=0` gives the previous selection exactly)

Code: `live/topic_div.py`, `scripts/daily_compose.py` (`diversity_prepare`, `diversity_order`,
`diversity_gate_hotspot`), `live/hotspot.py` (`reach_weight`).

- **Donor profile** per account (`topic_div.profiles`, cached in `live/store/topic_div/<day>.json`, aggregates only):
  the last 7 days of its donor cluster's original posts -> theme counts / mix, distinct themes and stories,
  entities named in the last 72 h. Themes: crypto split into lanes (stablecoin, regulation, institutional, security,
  perp, meme, airdrop, defi, ETH/L2, alt L1, CEX, AI x crypto, project events, on-chain, cycle / mood) plus the market
  topics of `posting_habits.TOPICS`. Crypto lanes apply only to text with a crypto mark.
- **Source tier** of every candidate, per account: 0 its own X source, 1 donor-adjacent (names an entity its donors
  named in the last 72 h, or a theme they spent >= 15% on), 2 other, 3 shared news (in >= 4 accounts' pools).
  A non-crypto account's own X post on crypto drops to tier 2.
- **Order**: (rewrite reuse, prescreen, timeliness) as before, then own sources, then a theme the account has not used
  today, then the other tiers, then stories no other account took yet, then themes inside the donor spread. All hard
  gates (beat gate, prescreen, licence, freshness window, per-language event cap) are unchanged.
- **Same story cap**: still at most 2 accounts per language, and now at most 3 accounts in all
  (`topic_div.MAX_TOTAL_PER_EVENT`). Events are the existing keys (source, source id, headline event, news hook, 母题).
- **Hotspots**: a WRITE stands only when the member the account would write from is tier 0 / 1 (else HOLD,
  `topic_div: ...`). The 母题 breadth term "accounts whose pool holds a member" has weight 0: it counted how many
  accounts share one feed, not public heat.
- `plan.json` carries `topic_div` (tiers per account, donor profile summary) and every pick a `topic_div` block
  (tier, theme, shared pools, adjacent entities).

## Own X posts without a fact unit (open)

On 10-08, 189 of 230 own-X (account, post) pairs in the 30 h window never reached a pool: judgment posts need a view
and a fact unit (`compose.eligible`), and the X extract mostly returned a view alone (89), a fact alone (47) or an
unusable view. Admitting view-only packets was tried and reverted: `compose_source` returns `not_suitable` for them
before any model call. A prompt variant asking for the fact a view rests on was A/B tested on 16 posts and did not
raise the share of fact + view posts (6 -> 5), so `x_units.EXTRACT` is unchanged. Breadth sources below raise the
number of composable own posts instead.

## X source breadth from the Sirius list (`live/x_breadth.py`, `scripts/x_breadth.py`, `live/x_breadth.json`)

- `candidates` (0 calls): Sirius handles not already ours, org-like handle names dropped, ranked by how often each
  account's donors @-mention them.
- `evaluate --max-calls N`: one twitter241 `/user-tweets` call per handle (user id known): activity, reply / repost /
  promo share, language, theme mix; `recheck`: `/user` for the org flag (square avatar / verified Business).
  Aggregates only, in `live/store/x_breadth/`.
- `assign`: individual, active, low-promo handles -> up to 2 same-language accounts by 0.6 x theme cosine with the
  account's 30-day donor mix + 0.4 x donor mentions, <= 8 per account; mostly-crypto handles never go to a
  non-crypto account. `exclude` in the config drops handles by hand.
- **Daily intake** (`x_daily.gather`, `FD_X_BREADTH`, default 1 when the config has handles): batched
  `/search-v2` `(from:a OR from:b ...) -filter:replies -filter:retweets`, Latest, up to `pages_per_batch` pages until
  the page is older than the window. Batches rotate by day when `daily_call_cap` cannot cover them. Posts then take
  the same filters, dedupe, per-handle cap and flash extraction as the CORE sources; units are scoped to the mapped
  accounts (`daily_compose.select` adds them to the account's handles). Call log:
  `live/store/x_breadth/<UTC date>.calls.jsonl` (no key, no text).
- The config holds handles, mapped accounts and scores only (author ids are read from each search page). No tweet text and no Sirius repo content is in git.

## Budget

`scripts/cron/daily_compose.sh` and `daily_compose.py --budget-usd` default to $8 (was $4: the 10-08 run stopped
after 15 of 40 drafts).
