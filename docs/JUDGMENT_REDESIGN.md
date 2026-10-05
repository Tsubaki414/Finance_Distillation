# FD judgment redesign — one page (2026-10-05)

**Goal:** matrix accounts stop sounding like info dumps. Judgment-led professional voices that can win paid promo deals. Satisfy Fiona on process; demo must look like lasting analyst accounts, not one-source digests.

**Root cause (agreed):** not mainly donor count —
1. **Selection** is info-heavy (fact packs crowd out mechanism / view / philosophy).
2. **Voice cards / signatures** list donor open/close moves but do not hard-enforce “judgment first, data as evidence.”
3. **Pipeline** is one-source → one-take, so accounts have no lasting view across days.

---

## Acceptance metrics (BEFORE code)

Ship this round only if a small demo (3 personas × 1 draft, mix ZH/EN) meets all of:

| # | Metric | Pass bar |
|---|--------|----------|
| A1 | Opening is a call | First line carries the account’s judgment (not a question, not a bare number/recap). Soft `no_judgment` finding fires when it fails. |
| A2 | Data is evidence | ≤40% of sentences are primarily numeric; no research-summary set-ups / bullet data lists. |
| A3 | Pack is not pure-data | When the unit pool has any non-fact unit (`mechanism` / `view` / `aphorism`), the compose pack includes ≥1 of them. Pure-fact packs only when no non-fact exists. |
| A4 | Signature open/close | Compose payload marks donor openings/closings as **hard constraints** (judgment-first open; landing close). Soft repair note if opening fails A1. |
| A5 | Lasting view | When a prior ledger view exists on the same subject, stance prefers **continue / update** that view (`revises_view_id`, or `continues_view_id` linked deterministically - see `docs/2026-10-05_continues_view_id.md`); fresh one-shot takes without acknowledging the prior are soft-flagged. |
| A6 | Demo feel | Blind skim: 2/3 drafts read as “analyst with a book,” not “newsletter digest.” Fiona sign-off on the 3 samples. |

**Out of scope this round (explicitly won’t do):** persona scale-to-1000, new donor scrapes, RapidAPI/X, big Gemini A/B burns, publish/outbox, hard-blocking drafts on voice (soft findings + one soft rewrite only), rewriting emotion tiers.

---

## What changes (one cluster)

### Selection (`live/compose.py` pick / choose)
- Prefer judgment-led post types when a `view` unit is available.
- `pick_units`: after recipe fill, if pack is all-`fact` and pool has non-fact, **inject ≥1** highest-ranked non-fact (cap pure-data-only packs).
- Expose `pack_balance` metadata on the draft for demos/tests.

### Voice (`compose` prompt + soft check)
- Signature `openings` / `closings` become **hard constraints** in the compose payload (not optional flavour).
- Prompt line: open with the call the way the signature opens; numbers only as support; close on a landing line from the signature closings family.
- Extend judgment-first soft check beyond `judgment_take` / `contrarian_take` to all compose post types that carry a stance; one soft rewrite on `no_judgment` / `data_list` when signature hard rules are present.

### Ledger (`live/stance.py` + `view_ledger`)
- When `prior_views` is non-empty, stance prompt requires: prefer continuing or updating the closest prior (`revises_view_id` when direction/conviction/horizon changes); do not invent an unrelated one-shot take on the same subject.
- Soft finding `ignores_prior_view` when take/adapt on an overlapping subject neither cites continuity nor sets `revises_view_id`.

---

## Demo checklist (stakeholder walkthrough)

Show, in order:
1. **Before feel** (label an overnight digest-y draft) vs **after** (judgment-led sample) for the same persona/theme when available.
2. Pack composition: unit kinds on the after draft (`pack_balance`).
3. Signature hard constraints visible in the compose payload (openings/closings).
4. Ledger: day-2 stance that continues/updates day-1 view on the same subject (or soft flag if it ignored).
5. Say clearly: drafts only, not published; AI-judge scores are reference; next gate is human rating + 7-day dry run.

Do **not** claim paid-deal readiness or scale. Frame: *draft factory with judgment memory and guardrails.*

---

## Success / fail for this PR

- **Success:** A1–A5 enforced in code + tests; 3 demo drafts written; redesign doc + brief dashboard card; suite still 22 baseline failures.
- **Fail:** only prompt wording changed with no selection/ledger enforcement; or fab/voice regresses badly on the 3 samples (report and stop — no large A/B).
