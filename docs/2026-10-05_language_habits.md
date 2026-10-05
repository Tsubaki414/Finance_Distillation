# Donor language habits + Fiona industry voice — 5 Oct 2026

## What shipped
1. `live/language_habits.py` builds aggregate cards from existing donor posts
   (`live/donors/posts/*.jsonl`, read-only). Cards live in
   `live/personas/language_habits/*.json` (shares, prefer/avoid, sample IDs only —
   no donor text). Compose attaches them under the same emotion payload switch as
   posting_habits.
2. Industry personas get `industry_constraints` (ZH 研报腔 bans + EN sell-side bans)
   merged into signature `hard_constraints`. COMPOSE prompt adds matching NEG/POS lines.
3. Signature card hygiene after Fiona comments:
   - `zh_industry`: rewrote「瓶颈搬家」so it no longer teaches「链路往下推」; removed
     「还早着呢」from lexicon/closings/zh_restraint; added anti-研报腔 taboos + POS restraint.
   - `en_industry`: taboos for valuation-free / supply-discipline filler; Fiona shape exemplar.
   - `en_macro` / `single_stock_deepdive_en`: stripped teaching of empty「That said」and「the catch?」.
4. Fiona #3/#4 rewrite text was not saved in notes (only lesson tags). Structural
   few-shot shapes are on `fiona_feedback_exemplars` for `market_data_charts` (#3:
   skeptical + levels) and `crypto_macro_en` (#4: rates vs ETF/OI), injected like
   zh_restraint. Soft phrase bans gained `is a start` / `that door closes`.
5. ORCL / stock price-direction freshness: **skipped** — no live quote feed or
   cached last-price series in-repo to soft-check against.

## Tests
`tests/test_language_habits_oct5.py` + prior anti_repeat/compose subset.
