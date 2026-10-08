# Draft images that look like the donors' (media v2, 2026-10-08)

Fiona (Oct 8): the images on FD drafts looked fake next to what the accounts' donor bloggers post.

## What donors post (sample of 2026-10-08)

Sample: the 40 most recent original posts of each donor (10 donors per account, 20 accounts) for the image rate.
6 recent donor images per account were downloaded through the public embed endpoint and classified by
gemini-3-flash-preview via the relay, then spot-checked by eye: 115 images, about $0.32. The images and the
classification stay in a local scratch dir (`/workspace/x/charts_real`) and are never committed.

- Image rate: 21–59% of original posts carry an image (zh_longterm_investing 0.21 … crypto_onchain_en 0.58).
- Only about half of those images are charts (crypto_zh 55%, crypto_en 59%, stocks_zh 50%, stocks_en 69%). The rest
  are memes and photos, X / news screenshots, text cards and event photos.
- Charts by family (share of chart images; n = 40 / 41 / 18 / 16 images, so ±10 points):

| family | TradingView | phone app (exchange / broker) | data panel (Glassnode / CryptoQuant / research / FRED) | table / funding / derivatives | light theme |
|---|---|---|---|---|---|
| crypto_zh | 23% | 23% | 36% | 18% | 64% |
| crypto_en | 42% | 4% | 46% | 8% | 46% |
| stocks_zh | 44% | 33% | 22% | 0 | 78% |
| stocks_en | 36% | 9% | 55% | 0 | 82% |

- Common traits: real tool chrome (TradingView legend, toolbars, the exchange app's price header and buttons, a
  status bar on phone shots), light about as often as dark, varied aspect ratios (tall phone shots 1080×2000+, wide
  desktop crops, panels), hand-drawn horizontal rays, boxes and arrows in TradingView drawing colours, no
  "fetched at" stamps, a source line or tool watermark on data panels.

## Why ours looked fake (Oct 7 path, `charts.attach_v1`)

- One template for all 20 accounts: dark `#131722` matplotlib, 1600×900, MA20 + MA50 always on, DejaVu Sans.
- A footer no human posts ("Data: Binance spot · last bar … · fetched … UTC") and a generic title ("TRXUSDT · 1D ·
  Binance spot").
- Every eligible draft got a chart. Donors attach one far less often, and roughly half of their images are not
  charts at all.
- No tool UI: no TradingView legend or toolbar, no phone app screen, no light theme. Panels and tables, which the
  on-chain and research accounts mostly post, were never produced.
- Off-topic charts: a draft that names a coin once in passing still got that coin's candles (for example, an
  L2-merger post got an ETH chart). Meanwhile chart_caption drafts on accounts whose beat regex did not match got
  no image at all.
- Levels as full-width dashed lines with boxed labels. People draw rays from where price touched the level.

## What changed

`live/media_real.py` (default; `charts.attach` dispatches to it). Per account, `live/media_profiles.json`
(aggregates only; rebuild with `scripts/build_media_profiles.py --classes … --meta …`):
`p_image = image_rate × chart_share`, style weights, light share, tall share.

Decision (`decide`, deterministic per draft id so apply_media and the hourly refresh agree):
- quote / reply posts: no image (the quoted card is the visual).
- chart_caption: always, when there is a subject.
- otherwise: an image with probability `p_image`.
- The subject must be what the draft is about: the ticker plus price or market words (or two mentions), or a data
  series. Crypto subjects never go on stock or investing accounts.
- Style is drawn from the profile among the feasible styles:
  - tv_widget: only when the draft names no levels, because the widget cannot be annotated.
  - table: only when the text talks funding, OI, leverage or liquidations.

Styles, best first:

| style | how | looks like |
|---|---|---|
| tv_widget | headless screenshot of TradingView's public embed widget (`s.tradingview.com/widgetembed`) | a real TradingView screenshot |
| panel (FRED series) | headless screenshot of the public FRED graph (`fred.stlouisfed.org/graph/?id=…`) | FRED chart as posted |
| tv_drawn | local HTML + TradingView Lightweight Charts (Apache-2.0) with our Binance / Yahoo bars; legend, optional toolbars, rays / box at the levels the draft names | TradingView desktop shot with drawings |
| mobile | same engine in a 390-pt phone frame: status bar, pair header, 24h stats, MA(7/25/99) or MA5/10/20, interval tabs, buy/sell (crypto); Futu-like red-up for zh stocks | exchange / broker app screenshot |
| panel | price vs 50/111/200-day SMA, or a FRED / DefiLlama series; Inter / Plex fonts, source line | Glassnode / research export |
| table | Hyperliquid (fallback OKX) public perp data: price, 24h, funding, OI, volume; the draft's coin highlighted | Coinglass-style funding table |

Fallback chain, never blocking a draft: capture → the rendered equivalent → the Oct 7 matplotlib chart (if the
account was eligible there) → no image (`media_plan.status = no_data`, with `tried` reasons). Captures run in a
subprocess (`scripts/chart_capture.py`, 90 s timeout) with a fresh headless browser context: no cookies, no login,
no profile, one page load per image. They use playwright's bundled Chromium when installed, else `FD_CHROME`
(default `/usr/bin/google-chrome`) headless. The capture Python is `FD_CAPTURE_PYTHON`, else the current
interpreter if it has playwright, else `python3`. Local HTML pages are offline (every non-file request is
aborted). Blank captures (low pixel variance) are rejected.

Numbers: every plotted value comes from a fetch, as before. Drawn lines are only prices the draft names
(`charts.draft_levels`). No "fetched at" stamp in the image; fetch URLs and times stay in the `.json` spec and the
media dict.

Other fixes: `fetch_crypto`'s cache key now includes `bars` (a 150-bar entry no longer answers a 1000-bar request
in the same hour). FRED DFII10 (real yields), ZEC / ONDO / TAO / WLD added. The ops page caps image height at
560 px, so tall phone shots stay readable.

Not changed: the 回看 then-vs-now chart (`live/archive_lookback.py`) still uses its fixed matplotlib render.

Attribution: Lightweight Charts™ is © TradingView, Inc., Apache-2.0. The library is downloaded at runtime
(sha256-pinned) into the chart cache, not vendored. Its in-chart logo is turned off. If these images are ever
shown on a public site, add the TradingView attribution notice there.

## Flags

- `FD_MEDIA_V2=0`: rollback to the Oct 7 path (`charts.attach_v1`, unchanged).
- `FD_MEDIA_CAPTURE=0`: no public-page captures; everything is rendered locally.
- `FD_CAPTURE_PYTHON`, `FD_CHROME`: override the capture interpreter or browser.
