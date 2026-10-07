# P0 crypto pilot sources (2026-10-06)

Scope: first slice of the PM material plan for three pilot accounts: `zh_airdrop_diary`, `zh_airdrop_tutorial`, `en_airdrop_farmer`. These are config stubs. Nothing here is a human source-quality label, and nothing auto-publishes.

## What was added

| file | change |
|---|---|
| `live/source_registry.json` | +11 feed/API sources and +15 X watchlist handles. All are `enabled: false` + `account_scoped: true`, so `analysis_corpus.subscriptions()` (global intake) never polls them. They are reached only through account universes. |
| `live/source_licence.json` | Feeds and exchange announcements are tier B (facts and paraphrase with attribution, no reproduction). X watchlist handles are tier C (topic lead only). |
| `live/owned_accounts.json` | Three pilot charters (`enabled: true`, `pilot` key). They are not added to `live/account_monitor.json`, so the daemon does not run them. |
| `live/account_source_universes.json` | Three universes (CORE / SECONDARY / EVENT_ONLY / RESEARCH_ONLY / WATCHLIST). Morris / zh_macro / zh_industry are unchanged. |
| `live/pilot_account_configs.json` | Per-account config stubs: post_type_mix placeholder, topic_scope, language, emotion, lighthouse_fit, source_universe_id, and donor handles only. These are not loaded as personas until voice, posting-habits and compliance cards exist. Style cards stay local. |
| `live/crypto_flash_hints.json` | Airdrop/TGE/points/testnet include/exclude regexes and a proposed WSCN blockchain flash outlet. These are hints only; `flashes.TOPIC` is unchanged. |
| `live/account_sources.py` | `source_key` accepts the registry `link_hosts` for feeds whose article host differs from the feed host (Odaily: `rss.odaily.news` → `www.odaily.news`). |

## Constraint that shapes the universes

**Update 2026-10-07 (user decision):** same-language sources are fine for the pilots, without attribution. The pilot charters in `live/owned_accounts.json` carry `allow_same_language: true`, and `admission()` skips the P0-1 same-language refusal only for accounts with that flag. Morris, zh_macro and zh_industry have no flag, so P0-1 still applies to them.
- zh pilots: Odaily post and ChainCatcher are CORE. Odaily flash and `crypto_wscn_blockchain` (WSCN 7x24 blockchain channel, account-scoped `flash_json` adapter; the global `flashes.OUTLETS` is unchanged) are SECONDARY. The English feeds are SECONDARY.
- EN pilot: airdrops.io and The Block are CORE. Cointelegraph and The Defiant are SECONDARY. Odaily and ChainCatcher are SECONDARY.
- Downstream, `AccountSourcePipeline.route` (adaptation) still refuses same-language material. Pilot compose needs its own same-language path before it can use these rows.

## Fetch verification (2026-10-06, plain HTTP, no LLM)

| candidate | url | kind | lang | status | items | registry id / note |
|---|---|---|---|---|---|---|
| cointelegraph | https://cointelegraph.com/rss | rss | en | ok | 30 | crypto_cointelegraph |
| decrypt | https://decrypt.co/feed | rss | en | ok | 57 | crypto_decrypt |
| theblock | https://www.theblock.co/rss.xml | rss | en | ok | 19 | crypto_theblock_news |
| coindesk | https://www.coindesk.com/arc/outboundfeeds/rss/ | rss | en | ok | 25 | ok; also existing channel ch115, not added |
| thedefiant | https://thedefiant.io/api/feed | rss | en | ok | 100 | crypto_thedefiant |
| blockworks | https://blockworks.co/feed | rss | en | fail | 50 | feed stale: newest item 2026-01-07 |
| airdrops_io | https://airdrops.io/feed/ | rss | en | ok | 10 | crypto_airdrops_io |
| airdropalert | https://airdropalert.com/feed/ | rss | en | ok | 10 | ok but mostly explainers; not added |
| odaily_flash | https://rss.odaily.news/rss/newsflash | rss | zh | ok | 10 | crypto_odaily_flash |
| odaily_post | https://rss.odaily.news/rss/post | rss | zh | ok | 10 | crypto_odaily_post |
| panews_zh | https://www.panewslab.com/rss/zh/index.xml | rss | zh | fail | 0 | 404 on guessed RSS path; HTTPError: HTTP Error 404: Not Found |
| chaincatcher | https://www.chaincatcher.com/rss/clist | rss | zh | ok | 486 | crypto_chaincatcher |
| foresight | https://foresightnews.pro/rss | rss | zh | fail | 0 | returns HTML app shell, not RSS; ParseError: syntax error: line 1, column 0 |
| blockbeats_flash | https://api.theblockbeats.news/v1/open-api/open-flash | json | zh | fail | 0 | 200 but empty data[]; no items parsed |
| jinse_lives | https://api.jinse.cn/noah/v2/lives | json | zh | fail | 0 | DNS failure; URLError: <urlopen error [Errno -2] Name or service not known> |
| wscn_crypto | https://api-one-wscn.awtmt.com/apiv1/content/lives | json | zh | ok | 20 | (flash hint) wscn_blockchain_flash |
| defillama_raises | https://api.llama.fi/raises | json | en | fail | 0 | 402: raises endpoint is paid; HTTPError: HTTP Error 402: Payment Required |
| binance_new_listing | https://www.binance.com/bapi/composite/v1/public/cms/article/list/query | json | en | ok | 20 | crypto_binance_listings |
| binance_latest_activities | https://www.binance.com/bapi/composite/v1/public/cms/article/list/query | json | en | ok | 20 | crypto_binance_activities |
| bybit_new_crypto | https://api.bybit.com/v5/announcements/index | json | en | fail | 0 | 403 from this host; HTTPError: HTTP Error 403: Forbidden |
| okx_announcements | https://www.okx.com/api/v5/support/announcements | json | en | ok | 20 | crypto_okx_listings; ok; newest listing ~2026-07-30 (low frequency) |
| coinmarketcap_airdrops | https://coinmarketcap.com/airdrop/ | html | en | fail | 4 | client-rendered; only empty headings, no items |
| cryptorank_airdrops | https://cryptorank.io/drophunting | html | en | fail | 0 | 403 (bot wall); HTTPError: HTTP Error 403: Forbidden |


The Binance/OKX announcement APIs have no account refresh adapter (`adapter: json_api`). They are EVENT_ONLY and enter only through an explicit `intake --input` JSON import.

## X watchlist (twitter241 `/user`, 20 calls)

None of these handles are persona donors. Their role is WATCHLIST: topic lead only, no candidates, and no implicit X spend.

|---|---|---|---|---|
| handle | status | followers | verified_type | note |
|---|---|---|---|---|
| @binancezh | ok | 466040 | Business |  |
| @BinanceWallet | ok | 2854520 | Business |  |
| @Galxe | ok | 1509064 | Business |  |
| @layer3xyz | ok | 724523 | Business |  |
| @OdailyChina | ok | 73412 |  |  |
| @ChainCatcher_ | ok | 46802 |  |  |
| @BlockBeatsAsia | ok | 88396 |  |  |
| @PANewsCN | ok | 100051 |  |  |
| @WuBlockchain | ok | 559163 | Business |  |
| @lookonchain | ok | 712761 |  |  |
| @CryptoRank_io | ok | 557933 |  |  |
| @DefiLlama | ok | 371997 |  |  |
| @DropsTab | fail |  |  | not found -> use Dropstab_com |
| @TheBlock__ | fail |  |  | not found -> use TheBlockCo |
| @binance | ok | 16165826 | Business |  |
| @AirdropsIO | ok | 202 |  | impostor/dormant (202 followers, 1 post) - rejected |
| @TheBlockCo | ok | 595652 | Business |  |
| @Dropstab_com | ok | 109606 |  |  |
| @airdrops_io | ok | 161730 |  |  |
| @OKXWallet | fail |  |  | not found - not used |

Per account:
- zh_airdrop_diary: binancezh, BinanceWallet, Galxe, layer3xyz, OdailyChina, BlockBeatsAsia, lookonchain
- zh_airdrop_tutorial: binancezh, BinanceWallet, Galxe, layer3xyz, PANewsCN, ChainCatcher_, CryptoRank_io, DefiLlama
- en_airdrop_farmer: Galxe, layer3xyz, CryptoRank_io, Dropstab_com, airdrops_io, DefiLlama, TheBlockCo, lookonchain

## Ingest smoke (temp store, zero model calls)

`refresh(store, <pilot>, limit=12, max_sources=12)` into a throwaway Store. Details are in `runs/p0_crypto_pilot_20261006/ingest_smoke.json`.

| account | feeds fetched | admitted → inbox | pending_selection | needs_source |
|---|---|---|---|---|
| zh_airdrop_diary | 5 | 13 | 11 | 2 |
| zh_airdrop_tutorial | 5 | 13 | 11 | 2 |
| en_airdrop_farmer | 3 | 6 | 1 | 5 |

Known noise: the topic terms `融资`, `交互` and `points` admit some off-beat items (AI funding, macro). airdrops.io guides are often older than the monitor's 72h age window.
