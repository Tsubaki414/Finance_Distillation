# Mind-map fill tier + long-form source ingest (Oct 16, Fiona)

Fiona (16 Oct 2026): the book / blog mind-map series and blog / video-transcript fetching are part of the regular nightly
pipeline. Mind maps are **not an account**; they are a post type used as the **last tier of the fill-slot logic**.

## Tiers for an account's day
1. fresh standalone drafts (compose rounds) and reply / quote drafts (engagement slot)
2. 回看 / 常青 archive drafts (`live/archive_lookback.fill_gaps`, `FD_ARCHIVE`)
3. **mind map** (`live/mindmap/fill.py`): only when the account still has **no ready standalone row** (not held, not
   superseded, draft_ready, non-engagement; an archive row counts as standalone; reply rows do not) - the same slot rule as tier 2.
   A mind-map row yields its slot to a later fresh standalone (`archive_fallback.is_archive` covers `post_kind=mindmap`).

Hook: `scripts/daily_compose.py` after the 回看 hook and before the final one-per-story / fresh-hold sweep.

## Account tone gate (Oct 16, Fiona: "don't fill reply-only accounts; account tone (账号调性) decides")

- **Reply-only accounts are not filled.** `fill.gate` refuses when the account has any live (not superseded / held) reply or
  quote row and no ready standalone. Only an account with no standalone *and* no engagement rows for the day is filled.
- **Tone allow list**: `live/mindmap_accounts.json` (`eligible`) lists the analytical / educational / long-term accounts
  (macro, research, BTC-cycle, newbie education, long-term investing, single-stock deep dive). Hype / trader / arb /
  airdrop / options / perks / meme / prediction / flash accounts are not in it. **Unknown accounts are not eligible.**
  `FD_MINDMAP_ACCOUNTS` (csv), when set, overrides the file. A missing / unreadable file means nobody is eligible.
- **Topic fit**: besides `topic_fits`, `fill.lane_check` runs `live/lane_fit` (`macro_check`, `packet_check` for niche
  accounts) on the source title + topic. An off-lane source (e.g. a TSMC earnings map on a bitcoin-cycle account) still
  yields a row, but it is held: `held=true`, `hold_reason='off_lane'`, `draft_status='needs_review'`.

## Flags
| env | default | meaning |
|---|---|---|
| `FD_MINDMAP_FILL` | `0` (nightly script sets `1`) | enable tier 3 |
| `FD_MINDMAP_MAX_PER_DAY` | 4 | mind maps per Beijing day (all accounts) |
| `FD_MINDMAP_BUDGET_USD` | 1.0 | model spend per run |
| `FD_MINDMAP_ATTEMPTS` | 3 | sources tried per account |
| `FD_MINDMAP_MAX_TRIES_PER_RUN` / `FD_MINDMAP_WALL_S` | 12 / 1500 | source tries (each 1-3 flash calls, ~30 s each) and wall-clock cap per compose run |
| `FD_MINDMAP_ACCOUNTS` | all in run | csv allow-list |
| `FD_MINDMAP_ITEM_MAX_USES` | 3 | max accounts per source item |
| `FD_MINDMAP_VIDEO_POOL` | 1 | include FD_VIDEO_SRC transcripts (only its 2 accounts; money / mind-set titles) |
| `FD_MINDMAP_PYTHON` | `/usr/bin/python3` | interpreter with playwright (+ `/usr/bin/google-chrome`) for the PNG |
| `FD_MINDMAP_STORE` | `live/store/mindmap` | ledger + run dirs |
| `FD_LONGFORM_SRC` | 1 | fetch step on/off |
| `FD_LONGFORM_DIR` / `FD_LONGFORM_CONFIG` | `/workspace/x/longform_src` / `live/longform_sources.json` | store / source list |
| `FD_LONGFORM_BUDGET_S`, `FD_LONGFORM_ASR`, `FD_LONGFORM_ASR_MAX`, `FD_LONGFORM_ASR_MAX_S` | 900, 1, 2, 1500 | fetch wall-clock, whisper fallback on/off, videos per run, max video length |

## Source ingest (`live/longform_src.py`, config `live/longform_sources.json`)
`daily_ingest` step `longform_start` starts a detached child (`python -m live.longform_src collect`, no LLM, never waited
for; `--no-longform` skips). Blogs: RSS (feed `content` or the article page via bs4), <= 2 new per source, <= 21 days.
YouTube: channel RSS -> captions via yt-dlp; **this box gets HTTP 429 on the caption endpoint**, so the default path is audio
download + the FD_VIDEO_SRC faster-whisper child (<= 2 videos / run, <= 25 min each). FD_VIDEO_SRC transcripts
(`/workspace/x/video_src`) and hand-placed book summaries (`<dir>/books/*.txt` + optional `.json` meta: title, author, lang,
topic, url) join the pool. The seed list reuses blogs already in `live/source_registry.json` (Lyn Alden, Damodaran, Hayes,
Wolf Street, Net Interest, The Overshoot, Moontower, Doomberg, Farnam Street, 海豚研究, Vitalik) plus 7 YouTube channels.

## Generation / checks (`live/mindmap/gen.py`) and render (`live/mindmap/render.py`)
One Gemini call (compose stage client, `FD_GEMINI_PROVIDER`) returns the tree + caption. Each L2-L4 node carries a verbatim
source excerpt `q`; nodes whose excerpt is not in the source, or whose numbers are not in the source, are dropped; > 25 % dropped =
HARD `mm_unsupported`. Shape (30-64 nodes, <= 4 levels, label length per language, glyph whitelist = no emoji / tofu), caption
checks (own voice, no @ / credit line / hashtag / emoji / return claim / contrast frame). The model may `skip` an off-topic source.
PNG: editorial paper (#F4EFE6, serif headings, one brick accent, no gradient / icon / pill), 1700 css px at 2x; the render
self-checks node-box overlaps / overflow (a failing render is not written). Credit (author, title, date, host, "paraphrased, not a
quote") is added deterministically as the image footer and in `row['mindmap']['attribution']`; the caption never carries a credit line.

## Row
`post_kind` / `post_type` `mindmap`, label 思维导图, `media[0].kind = 'mindmap'` (`<FD_MEDIA_OUT>/media/<day>/mm-*.png`), `source`
(id, publisher, title, url, published_at), `mindmap{nodes, levels, stats, attribution, tree_json}`, freshness-exempt
(`fresh_hold.check`), held + `needs_review` when a hard finding fires. Never publishes.
