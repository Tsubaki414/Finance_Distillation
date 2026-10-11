# 周年 / anniversary source (FD_ANNIV, default on)

Well-known dated events (BTC whitepaper, genesis block, Pizza Day, halvings, The Merge, FTX, LUNA/UST, Lehman,
Black Monday, the 10/10 2025 liquidation crash ...) were in none of our sources; `archive_lookback` only mines the
accounts' own sources from a year ago.

- `live/event_calendar.json` - curated events: `id`, `date`, `kind`, `lane`, `title_en/zh`, optional `facts` /
  `facts_zh` (the only event facts a draft may use), `subject` (then-vs-now series), `accounts` (lane allowlist),
  `sources`, `verify`. Only `verify.status == "ok"` events are used.
- `scripts/verify_event_calendar.py` - re-checks every date against its source page (Wikipedia via the parse API,
  others fetched; date spellings / day-month near the year), `price_extreme` events (ATHs, cycle lows) against
  Binance / Yahoo daily data; `manual_webfetch` records pages that block scripted fetches. `--write` updates `verify`.
- `live/anniversary.py` - `pick(day)`: events whose 1/2/5/10-year (and every 5th above 10) anniversary is within
  +-1 day of the Beijing day -> packet with dated THEN / NOW / CHANGE data (charts.py cache), facts, sources and the
  frame. Accounts: curated allowlist, beat gate, BTC/ETH macro lane, lane_allow when present, free slot
  (< 2 ready), one anniversary draft per account per day; <= 2 accounts per event, <= 2 per language, twins never
  both, <= 3 events per day. `run(day)` (daily_compose hook, before 回看) drafts one post per (packet, account) and adds
  it to the inbox (post_kind `anniversary`, label 周年, sources in `support_citations`, never publishes).
- Checks (HARD, one rewrite then HOLD): stale_frame (look-back frame + today comparison), anniversary wording, every
  number grounded in the packet, editorial_style HARD codes.
- Env: `FD_ANNIV=0` off, `FD_ANNIV_YEARS`, `FD_ANNIV_ROUND5`, `FD_ANNIV_WINDOW`, `FD_ANNIV_PER_DAY`,
  `FD_ANNIV_ACCOUNTS_PER_EVENT`, `FD_ANNIV_MAX_READY`, `FD_STORY_PER_LANG_DAY`, `FD_ANNIV_STORE`.
