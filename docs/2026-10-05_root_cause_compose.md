# 2026-10-05 · COMPOSE root causes (not more phrase bans)

Fiona's comments on the Oct 5 drafts kept naming the same symptoms: 信息罗列, research-note
cadence (研报腔), a glued-on「我的判断：」label, and emotion that doesn't come through. Each round
we banned the specific phrase. The phrases kept coming back because the **inputs** still taught
them. This change fixes the inputs.

## Symptoms → causes → fixes

| Fiona's symptom | Root cause in the pipeline | Fix (structural) |
|---|---|---|
| 第一句是数据/新闻/来源，research cadence | `signature_cards/*.json` `openings` taught data-first, source-first, news-recap and calendar opens (「先交代来源」「开头一句短陈述就是事实」「今晚市场真正的核心」「今晚有…数据要公布」, "sourced data point stated flatly"). COMPOSE says "judgment first" but the signature is marked **HARD voice law**, so the two rules fought each other and the card often won. | Rewrote the openings on all 10 cards so they lead with a judgment or call. Only `market_data_charts` / `trading_shortterm` keep one data-led opening, marked `[data_take only]`. COMPOSE now adds a HARD line telling the model to ignore `[data_take only]` openings for every other post type. |
| 信息罗列 + 「我的判断：」 glue | `RECIPES['judgment_take'/'contrarian_take']` = 1 view + **3 facts**. The model used every unit it got, so the post became a dump with the label stuck on as glue. `view_relay` (2) and `earnings_take` (4 facts) had the same problem. | Recipes are now 1 view + 1 fact (`view_relay` 1 support, `earnings_take` 2 facts). New `trim_judgment_pack()` caps the pack at 1 primary view (or a mechanism if there is no view) + **at most 2 facts**, chosen by freshness rank. It runs in `pick_units` for judgment types and runs again once a stance with `account_view` exists. |
| Colleague drafts feel like a person with a view; ours feel synthesized | **Colleague gap:** they lock the thesis first and then write thin evidence. We hand the model a fat pack and ask it to synthesize, so the thesis comes out of the evidence and lands mid-post. The emotion contract exists, but it gets buried under 4+ units. | When a stance exists the payload now carries `thesis_lock` (= `stance.account_view`) and `evidence_budget: {max_numbers: 2, unused_units_ok: true}`. COMPOSE says: line 1 = paraphrase of thesis_lock with no meta-label, "You MUST leave surplus units unused", at most 2 numbers. |
| 「我的判断：」 keeps coming back | (a) The COMPOSE first-person allowlist included "我的看法". (b) The `zh_macro` lexicon contained「我的判断：」. (c) The `zh_macro` restraint exemplars and top signature exemplar (the Btcxiaoyuan「今晚市场真正的核心」post) contained the label. | Removed it from the allowlist, the lexicon (moved to `lexicon_dropped`), `donor_first_person`, and the restraint shapes. Dropped the 真正的核心 exemplar from the signature exemplars (its id stays in `sample`). The builder now rejects exemplars with the label. |
| 研报腔 for industry | The raw donor exemplar shown for zh_industry was a 7-point source-first supply-chain list (補充郭明錤…). | For judgment posts, when a Fiona POS shape or ZH restraint shape is available, the long raw signature exemplar is skipped. data_take still gets it. `zh_industry` / `en_industry` now have card-level `hard_constraints` (judgment first; ≤2 numbers; no 研报腔; end on a falsifiable call; leave unused units unused; no「我的判断：」wrappers), and COMPOSE forwards them into `signature.hard_constraints`. |

## Soft check

`compose.info_dump_findings`: for judgment_take / contrarian_take, a body with ≥4 distinct
numbers, or ≥3 data clauses split by ；/、, gets a **soft** `info_dump` finding. It never
hard-blocks. `research_summary` (semicolon chains / bullet lists) still exists; `info_dump`
adds the number budget on top of it.

## What changed in code
- `live/compose.py`: RECIPES, `JUDGMENT_MAX_FACTS`, `EVIDENCE_BUDGET`, `trim_judgment_pack`,
  `info_dump_findings`, payload `thesis_lock` / `evidence_budget`, COMPOSE prompt (minimal),
  card `hard_constraints` forwarded, `[data_take only]` rule, raw donor exemplar skipped for
  judgment posts when POS / restraint shapes exist.
- `live/qa_levels.py`: `info_dump` is SOFT, with a fix line.
- `live/personas/signature_cards/*.json`: openings rewritten (+ `openings_note`); industry
  `hard_constraints`; zh_macro label / 真正的核心 cleanup.
- `scripts/build_signature_cards.py`: a rebuild keeps the curated keys (openings,
  hard_constraints, restraint / Fiona shapes) and rejects exemplars that carry「我的判断：」.
- `tests/test_rootcause_compose_oct5.py`: recipe counts, trim, thesis_lock payload, banned
  opening teaching, data-only labelled opening, info_dump soft.

## Still needs Fiona's eyes
- Upstream stance text: some `stance.account_view` values in older fixtures still contain
  banned cadence (e.g. "valuation-free optimism", 「才是关键」). thesis_lock now pins line 1 to
  the stance, so stance quality matters more than before.
- Whether one fact is too thin for some judgment posts (the trim allows 2; the recipe gives 1
  unless balance or the stance adds more).
- The emotion contract is unchanged. Thin packs should give it room, but there is no new emotion
  logic in this change.
