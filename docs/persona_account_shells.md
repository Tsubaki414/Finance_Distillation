# Persona account shells（十人设）

给运营配号用：显示名 / handle / bio / 头像方向。内容人设见 `live/accounts.json` 与 `live/personas/`。

| persona_id | 显示名 | handle | bio | 情绪档 | 头像方向 |
|---|---|---|---|---|---|
| `zh_macro` | 口径先行 | `@koujing_macro` | 宏观数据与政策机制｜先拆口径再谈方向｜不报仓 | mid | 简洁深色底 + 折线/柱状抽象图标，无真人脸 |
| `en_macro` | Print Check | `@printcheck_macro` | Macro prints & policy mechanics. Call first, data second. No positions. | low | Minimal navy mark, yield-curve or print glyph, no face |
| `zh_industry` | 链路拆解 | `@lianlu_industry` | 产业与供应链｜表面 vs 实质｜AI capex / 财报可读点 | mid | 几何节点/链路图标，冷色工业感 |
| `en_industry` | Capex Wire | `@capex_wire` | Industry & supply chain. AI capex, earnings, what the release hides. | mid | Circuit/node motif, steel blue, no face |
| `crypto_macro_zh` | 链上宏观笔记 | `@onchain_macro_zh` | BTC · 稳定币 · 监管｜宏观联动，少喊单 | high | 深色 + 简单链环/烛线符号，偏锐利 |
| `trading_shortterm` | Skew Desk | `@skew_desk` | Options positioning · dealer hedges · short-horizon structure. Not advice. | high | Volatility smile / skew curve icon, black-green terminal feel |
| `market_data_charts` | Breadth Check | `@breadth_check` | Breadth, sentiment, flows. One chart, one call. | high | Simple breadth bar chart mark, high contrast |
| `investing_philosophy` | Margin of Error | `@margin_of_error_` | Risk, behavior, long-horizon principles. Aphorisms with teeth. | low | Serif monogram or balance-scale abstract, muted cream/ink |
| `single_stock_deepdive_en` | Filing First | `@filing_first` | Earnings & filings first takes. Number vs number. No portfolio flex. | low | Document/ticker glyph, clean grayscale |
| `crypto_macro_en` | Onchain Macro | `@onchain_macro_en` | BTC, stables, regulation. Macro first. Flows over vibes. | high | Dark theme, on-chain node glyph, sharp |

## 配号说明

1. handle 若被占用，保留语义词根改后缀数字即可。
2. bio 不写机构背书、不写持仓、不写“by research lab”。
3. 头像统一用抽象图标，不用真人/伪造证件照。
4. 机器可读副本：`docs/persona_account_shells.json`。
