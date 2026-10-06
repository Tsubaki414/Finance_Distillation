# Footer credit for generic sell-side sources (2026-10-06, v4)

**Decision: keep a footer, change its format.** "Source: sell-side research" read like a byline on a
pro account (PM review of v3), but the footer cannot simply be dropped:

- `live/source_licence.json`: tier **B** = "analysis to paraphrase **with attribution**"; every
  `reportgem_*` bank entry is tier B, and the ReportGem MCP entry carries
  `attribution_required: true` (Fiona decision 2026-10-04, paraphrase only, no reproduction).
- `live/source_display.json`: `sell_side_credit: "generic"` (2026-10-04 night) - the bank and
  ReportGem are never named; the credit is the generic "sell-side research" / "券商研报".

So attribution is required and stays generic. The **format** is now a neutral reference line, not a
"Source:" byline - only for the generic policy (`credit_policy != 'name'`):

| lang | before | after |
|---|---|---|
| en | `Source: sell-side research` | `(ref: sell-side research)` |
| zh | `（来源：券商研报）` | `（参考：券商研报）` |

Named sources are unchanged (`Source: Chipstrat`, `（来源：国家统计局）`). Implemented as
`template_generic` / `template_generic_en` on the `footer_source` frame in `live/post_types.json`,
picked in `attribution_frame.render`. The body still never credits the view (never_name +
`generic_credit_in_body`, v3). To restore the old line, delete the two `template_generic*` keys.
If the owner later rules that generic sell-side needs no attribution, the right change is a licence
entry (`attribution_required: false`), not a frame hack.
