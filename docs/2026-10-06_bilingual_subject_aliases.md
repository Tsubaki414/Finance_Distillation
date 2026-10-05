# Bilingual (ZH↔EN) subject aliases in the view ledger (2026-10-06)

## Problem
`continue_score` / `related()` / `contradictions()` / `ignores_prior()` overlap EN stems against ZH
bigrams. A zh persona whose prior view subject is Chinese («美联储降息路径») and whose new unit/stance
subject is English ("Fed rate cut path") scored 0.0 → `fresh` instead of `continue` (Oct 5 sim), and
cross-language flips went unflagged.

## Change
`live/finance_aliases.py`: a deterministic lookup table (64 concepts, 281 aliases: EN regex patterns,
letter-bounded, case-insensitive; ZH literals). `view_ledger._tokens` now:
1. `canonicalize(text)` – leftmost/longest alias hits become language-neutral `@concept` tokens
   (`美联储`/`Fed`/`FOMC`/`Powell` → `@fed`; `降息`/`rate cut` → `@rate_cut` + `@rates`;
   `制造业PMI`/`manufacturing PMI` → `@pmi` + `@manufacturing`; `比特币`/`BTC` → `@btc` + `@crypto`; …)
   and are cut out of the text;
2. the residual segments are tokenized exactly as before (`compose._tokens`), per segment, so ZH
   bigrams never straddle an alias span.

Every ledger overlap (continue-link, `related()`, flip detection, ignores-prior) goes through this one
tokenizer, so both directions are covered. No LLM / translation in the hot path.

**Thresholds unchanged** (`CONTINUE_SUBJECT_MIN = 0.4`, `CONTINUE_TEXT_MIN = 0.3`). Same-language
peers map identically on both sides, so their scores barely move; hierarchical concepts (rate cut →
also `@rates`) keep "rate cut" vs "rates" peers overlapping. Entities stay distinct (Fed ≠ ECB ≠ PBoC,
BTC ≠ ETH) so aliases do not merge different issuers/assets.

## Calibration (Oct 5 eve sim ledger, all pairs rescored)
| pair | old (subj, text) | new |
|---|---|---|
| trading_shortterm R1→R2 (EN-EN) | 0.40, 0.32 | 0.50, 0.39 |
| zh_macro 中国制造业产出 day1/day2 | 1.0, 1.0 | 1.0, 1.0 |
| all cross-topic pairs | ≤ 0.05 | ≤ 0.05 |

Unit pairs (tests/test_view_ledger_bilingual.py): 美联储降息路径/Fed rate cut path, 制造业PMI/
manufacturing PMI, 美债收益率/Treasury yields, 比特币ETF资金流/Bitcoin ETF flows, 通胀预期/
inflation expectations, 非农就业/nonfarm payrolls, VIX波动率/VIX volatility all ≥ 0.4 both ways;
six unrelated cross-language pairs ≤ 0.05; cross-language opposite direction is still a flip
(`unacknowledged_flip_of` + `contradicts_prior_view`).

## Limits
- Coverage is only the table: long-tail subjects (single names, sectors beyond memory/semis/property,
  niche macro series, policy jargon) remain language-bound and still go `fresh` cross-language.
- Generic concepts (`@path`, `@outlook`, `@supply`, `@rates`) can raise overlap between different
  entities that share framing ("Fed rate cut path" vs "ECB rate cut path" scores 0.75 – same as the
  pre-existing EN-EN behaviour; the alias layer does not add an entity veto).
- Alias hits are substring/regex based: no word segmentation for ZH, so e.g. `存储` inside an
  unrelated compound will still fold to `@memory`. Short EN aliases (`ai`, `fx`, `qe`, `eth`) are
  letter-bounded only.
- `pricing` was intentionally NOT aliased to `@expectations` (it inflated a cross-topic sim pair).
