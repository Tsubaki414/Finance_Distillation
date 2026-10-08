# Draft images from the donors' own sources (media v3, 2026-10-08)

Fiona, Oct 8: v2 still looked different from the donors. "看看他们的source都是什么；然后去source找": find out where the
donors' images come from and take ours from the same places, instead of drawing look-alikes.

## Where donor images come from

- **Sample.** 263 recent donor images (Oct 1–7), about 15 per account across the 20 accounts' donors.
- **How each was attributed.** Every image was traced by hand to the site, app or page it came from. Evidence used:
  - logo, watermark and UI chrome, read from labelled contact sheets;
  - the post's own links, @mentions and "source / 来源" lines;
  - OCR of the image.
- **Model use.** The vision-model relay was out of balance (HTTP 403), so no model was used.
- **Storage.** Images and per-image labels stay in a local scratch directory and are never committed.

| # | source | share of all donor images | can we take it? |
|---|---|---|---|
| 1 | not a chart (photos, memes, promos, chats, AI images, text cards) | 33.5% | no |
| 2 | TradingView | 11.8% | yes: official widget (v2) |
| 3 | the donor's own chart / infographic / table | 11.4% | rendered analog (v2 panel / table) |
| 4 | third-party research / bank report chart | 4.6% | no (reports, often paid) |
| 5 | news article / flash screenshot | 4.6% | mostly manual (see terms below) |
| 6 | Binance app | 3.0% | phone app: v2 mobile render |
| 7 | X post screenshot | 3.0% | **yes: official embed (new)** |
| 8 | Bloomberg terminal / app | 2.7% | paid |
| 9 | project / dapp UI | 2.3% | manual |
| 10 | CryptoQuant | 2.3% | manual (terms) |
| 11 | Glassnode (Studio / research figures) | 1.5% | manual (terms) |
| 12 | OKX app, DEX wallet apps, other broker apps | 1.1% each | phone app: v2 mobile render |
| 13 | Hyperliquid UI, exchange web trade pages | 1.1% each | manual (US geo block / terms) |
| … | DefiLlama, Trading Economics, Velo, Token Terminal, Futu, MarketSurge, StockCharts | 0.8% each | see below |
| … | ETF flow dashboard, Polymarket, CME FedWatch, CoinGlass/CoinAnk heatmap | 0.4% each | ETF + Polymarket: **yes (new)** |

Notes on the table:
- By family, TradingView is 21.5% of crypto_en images but 5.4% of crypto_zh.
- crypto_zh leans on exchange apps (Binance/OKX, about 11%) and news/flash screenshots (6.5%).
- stocks_en leans on research and report charts, own charts, Bloomberg and MarketSurge.

## Which pages we may load

We load a page only if robots.txt allows the path **and** either:
- the site's terms do not forbid automated access, or
- the page is the site's official embed, meant for third-party display.

These were checked on 2026-10-08.

| source | robots | terms on automated access | here |
|---|---|---|---|
| X post (platform.twitter.com embed) | – | official embed product | **captured** |
| Polymarket (embed.polymarket.com) | allowed | no clause found; official embed | **captured** |
| Farside Investors ETF flow tables | allowed | no clause found | **captured** |
| SoSoValue ETF dashboard | allowed | no terms page found | **captured** |
| BlockBeats / PANews / Odaily flash pages | allowed | no clause found | captured when the draft's source is one |
| TradingView widget, FRED graph | – | official widget / public data | captured (v2) |
| CoinDesk | allowed | forbids robots / scrapers | manual only |
| The Block | allowed | forbids automated collection; manual social screenshots ≤4/month with credit | manual only |
| Glassnode (studio, research) | allowed | forbids bots / automated processes | manual only |
| CryptoQuant | allowed | forbids scraping | manual only |
| DefiLlama | allowed | forbids robots for any purpose (free API → our panel) | manual only |
| CoinGlass | allowed | forbids scraping / bulk extraction | manual only |
| StockCharts | `/c-sc/sc` disallowed | forbids programmatic access; manual reprint needs "Chart courtesy of StockCharts.com" | manual only |
| CME FedWatch | allowed | page resets headless connections (HTTP/2 error) | manual only |
| Trading Economics | allowed | 403 to headless | manual only |
| Google Finance / Trends | disallowed | – | no |
| Hyperliquid app | allowed | geo-restricted for US (the box) | no (API → v2 table) |
| Binance / OKX / Futu / Tiger apps, Bloomberg, MarketSurge, YCharts, The Daily Shot, bank research | – | app, login or subscription | no |

## What v3 does (`live/media_sources.py`, wired into `live/media_real.py`)

### New sources
- **x_post.** For a draft built on an X post (`source.url` is an x.com status URL, and the draft is not a quote or reply), we screenshot that post through X's official embed, in the account language and theme. The image is cropped to the post card and credited (`media.credit = "@handle on X"`).
- **etf_flows.** For ETF-flow talk (ETF plus inflow / outflow / 流入 / 流出, …), crypto accounts only:
  - light theme: the Farside table for BTC / ETH / SOL / ZEC, cropped from the page title to the table end;
  - dark theme: the SoSoValue dashboard (BTC / ETH / SOL), cropped from the summary cards to the fund table.
- **polymarket.** For drafts on a topic Polymarket prices (Fed decision, midterms, recession, shutdown):
  - the market is found through the public gamma search API: the most traded active matching event, then its leading outcome (at least 5%);
  - we capture the official market embed.
- **article.** When the draft's source is an allow-listed flash or article site, a phone-width shot of that page. No current ingest source maps here yet.

### Choosing the image
- **Profiles.** Built from the attribution: `scripts/build_media_profiles.py --attribution …`.
  - Style weights come from the attributed source mix, per account, blended with the account's family.
  - `p_image = image_rate × share of donor images in a source we can produce`. Non-charts and article screenshots are excluded from that share.
  - The Oct 8 numbers stay under `v2`.
- **Style draw.** A source that matches the draft's subject gets a fixed share of the draw (`SOURCE_SHARE`); the v2 styles split the rest by profile weight:

  | source matched | share of the draw |
  |---|---|
  | ETF flows | 75% |
  | odds talk naming a prediction market | 75% |
  | topic only (no prediction-market wording) | 35% |
  | X post | 50% |
  | article | 50% |

- **No source matched.** The draft draws exactly as in v2: same style, theme and seed.
- **Manual suggestions.** `media_plan.manual_sources` lists pages a reviewer may screenshot by hand, each with its exact URL and the reason it isn't automated:
  - the source article on CoinDesk, The Block, Glassnode research, …;
  - a CoinGlass heatmap for liquidation talk;
  - CryptoQuant / Glassnode charts for on-chain metrics;
  - FedWatch for rate odds;
  - DefiLlama for TVL / fees;
  - StockCharts for stocks.

  These pages are never loaded automatically.

### Capture rules
- Each capture runs `scripts/chart_capture.py` in a subprocess with a fresh headless context: no cookies, no login, one page load.
- Consent and geo banners are hidden with CSS, never clicked.
- The page text is checked for login walls, errors, 404 / 403, "Market not found" and empty pages.
- The PNG is cached per page per hour (X posts: per day) and shared across drafts.
- At most one load per host every 8 s.

### Fallback
- Chain: source capture → the draft's v2 style (capture → render) → the Oct 7 matplotlib chart → no image.
- A draft is never blocked.
- Source images are `chart_type: data`, so the hourly refresh rechecks them at most every 6 h.

## Flags

- `FD_MEDIA_SOURCES=0`: v3 off. v2 behaviour exactly: v2 profile numbers, no source candidates, same draws.
- `FD_MEDIA_CAPTURE=0`: no public-page loads at all. Source styles fail over to renders.
- `FD_MEDIA_V2=0`: the Oct 7 path, as before.

## What did not work

- TradingView's `widgetembed` ignores the `studies` parameter in both formats tried (`RSI@tv-basicstudies` and `STD;RSI`), so the widget cannot show the donors' indicators. Not shipped.
