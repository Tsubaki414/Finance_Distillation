# Source-monitoring research, 2026-09-27

Frozen notes for the implementation. This is not a source-pool expansion.
Handles and feeds below were checked in that round. Anything marked
UNVERIFIED was not given an identifier.

## What changed the design

- BestBlogs WeChat OPML has live finance feeds. 财联社, 点拾投资, 聪明投资者,
  中金点睛, 雪球, 华尔街见闻, 海豚研究, 半导体行业观察, 第一财经 all returned
  dated items. No RSS token was required. The Twitter OPML is AI/engineering
  plus Ray Dalio. It is not a FinTwit list.
- `nskselva/market-toolkit` last pushed 2024-02. Seed handles only.
- No maintained GitHub FinTwit list. Edwin Dorsey's lists are on the web,
  not in a repo. `@10kdiver` last post 2023-01. `@HindenburgRes` last post
  2025-01. `@Doomberg` is an empty account. Doomberg lives at
  `https://newsletter.doomberg.com/feed` (updated 2026-09-26).
  `@CitriniResearch` is empty. Use `@citrini` and
  `https://www.citriniresearch.com/feed`.
- `@FedGuy12` does not exist. Conks is `@conksresearch`.
- 洪灏 X is `@HAOHONG_CFA`. 沧海一土狗, 唐书房, 洪灏的宏观策略 have no
  verified WeChat id.
- WeChat is a second-wave analysis layer. 财联社's public-account feed is
  not 财联社电报.
- X keyword search was HTTP 404. Account timelines hit HTTP 429.

## Feeds confirmed live that day

- `https://wechat2rss.bestblogs.dev/feed/8e9c7dfaf07013f4da379dd0f87c3a298f2ed501.xml` 财联社
- `https://wechat2rss.bestblogs.dev/feed/e2cc4ff2ae914ebfd4150420ece80dd93be7a6d9.xml` 第一财经
- `https://wechat2rss.bestblogs.dev/feed/60b1f9007c87ab75cd83314bf5cfede30addd40a.xml` 海豚研究
- `https://wechat2rss.bestblogs.dev/feed/5d4eef298108dd63ce77f40257436e0585bab425.xml` 中金点睛
- `https://wechat2rss.bestblogs.dev/feed/d141c2a7c08d56f573b32c7e2f09b6ee779dc51d.xml` 聪明投资者
- `https://xueqiu.com/hots/topic/rss` 雪球今日话题
- `https://newsletter.doomberg.com/feed`
- `https://newsletter.semianalysis.com/feed`
- `https://www.citriniresearch.com/feed`
- `https://www.netinterest.co/feed`

## Accounts read, not just profiled

- `@qinbafrank` 2026-09-27 blocked vs frozen wording on Iranian funds in China
- `@Murphychen888` 2026-09-27 on-chain BTC cohort
- `@EmberCN` 2026-09-27 THORChain
- `@PhyrexNi` mixed market and promo
- `@DeItaone` 2026-09-26 Cuba, not Hormuz
- `@NickTimiraos` 2026-09-25 Fed
- `@dylan522p` 2026-09-26 HBM
- `@xingpt` travel post, not research
- `@kovainvest` slogan, not research
- `@10kdiver` inactive
- `@HindenburgRes` inactive

## Hormuz case, as far as it was verified

Earliest English index: France 24, 2026-09-26 02:06 UTC, Google News.
Earliest Chinese index in the same pull: 央视网, 03:45 UTC.
First body actually read: BBC, 2026-09-27 02:16 UTC,
`https://www.bbc.com/news/articles/cmvgyyw2jeego`.
Friday settlements, wire-reported, not exchange tape: WTI 92.41, Brent 104.32.
WSJ midterms-bombing line is headline only.
`@qinbafrank` is a related wording event, not the same event.
Fixture: `live/research/hormuz_20260926.json`.
