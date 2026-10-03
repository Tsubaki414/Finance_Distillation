# Owned-account intelligence: historical implementation plan

> **SUPERSEDED — 2026-09-30 account-first correction.** The account-first design is [三个账号的信息世界与 source discovery 计划](ACCOUNT_SOURCE_UNIVERSES_PLAN.md); authoritative current scope and remaining work are in [CURRENT_DELIVERY_PLAN.md](CURRENT_DELIVERY_PLAN.md). Do not restore event-to-all-account expansion or demote Morris to a generic frameworks research input. The user subsequently approved execution, and the account-scoped runtime, dashboard entrypoint and persistent monitor have been connected. Operational/content acceptance remains incomplete; see the dated [P0 delivery evidence](../runs/account_monitor/p0_relay_live/DELIVERY.md). The text below preserves the previous implementation and its limitations, not the current product specification.

Date: 2026-09-30. Status: implementation and first real replay completed; content acceptance and human-adopted account state remain pending. This supersedes translation-only product development, not the immutable localization experiments.

## Product contract

An owned account decides whether to speak about an event using the information available at a stated time and its explicitly adopted state. Research from other authors supplies possible frameworks, examples and observations. It never supplies an invented personal history, automatically adopted opinion, or proof that a historical claim remains current.

The new opt-in path is:

`immutable sources → behavioral research units + hygiene annotations`

`event / evidence snapshot + account charter + adopted state + human decision history + relevant research → speak / wait / ignore → angle and evidence selection → two independent candidates → machine checks → human review → optional publication linkage / measured feedback → proposed or explicitly accepted state changes`

Cross-language translation remains available in the existing workbench. Source order is preserved when translating; original event commentary may have its own structure. These are distinct treatments, not conflicting writer instructions.

## Implementation sequence

1. **Data and time contract.** Preserve source identity, exact excerpts, timestamps, capture provenance and missing context. Import existing captured primary evidence and source records. Event facts carry evidence IDs, date, known-at, capture time and evidence role. Reject future evidence; distinguish historical replay from current operation. Do not infer deliberate silence or event triggers from missing archive posts.
2. **Research units.** Annotate behavior, topic, stance/confidence, durable/transient and personal/transferable content, examples, format and source relationship. Exact quotes and source IDs are validated. Editorial treatment is per unit; personal evidence can be retained with attribution where necessary. Unreviewed units remain research, not truth or account memory.
3. **Five owned charters and state.** Preserve existing IDs/languages in a separate opt-in charter file. Morris becomes a research input for the English frameworks account; no fake Morris identity. Store proposed/adopted/retracted state and revisions append-only. State snapshots use both effective and recorded time; generation and publication alone do not adopt a belief. Historical accounts start honestly cold.
4. **Event decision and candidate generation.** Evaluate every enabled account against the same event, its audience, existing views, prior explicit human decisions and selected research. Record speak/wait/ignore, stance relationship, rationale, missing evidence and chosen facts. Only speak reaches generation. Generate two candidates; retain actual failures. No automatic repair/tuning while collecting this pilot.
5. **QA and human feedback.** Separate machine factual/numeric/identity/temporal/stance checks from editorial review. Check guidance as well as copy. Human edits record exact text, reasons and categories; decisions to ignore/wait are explicit labels. Publishing remains external and can only be linked to an approved exact version. Feedback informs subsequent decisions through retrieval; engagement is contextual evidence, never an automatic instruction to intensify claims. Training export contains actual human labels only.
6. **Dashboard and evidence of execution.** Extend the local FastAPI workbench with events, all five account states, research units, decisions, two candidates, private QA, human controls and feedback. Run offline/API regressions plus a bounded real relay pilot; export full outputs and a compact blind-review packet. Preserve budget cap, production queue and frozen evaluation hashes.

## Acceptance scenarios

- ALAB: retrieve the connectivity framework while keeping the author's holding, timing and price assertions distinct; no ownership transfer or stale “today”. Attribution is an editorial choice, not an identity patch applied to everything.
- Morris: historical Chinese research can inform an English owned-account framework, without fabricating previous account beliefs or claiming an information advantage from translation alone.
- English primary macro evidence → Chinese and English macro decisions/candidates; company evidence → Chinese and English industry decisions/candidates. Routing is not restricted to opposite source languages.
- Inadequate/stale/promo evidence produces wait/ignore with zero writer calls. Missing media or exact supporting material cannot be declared verified.
- A newly accepted/revised/retracted view changes the state snapshot; previous generation and human approval become stale for publication. Future evidence and future state are unavailable in historical replay.
- Human approve/reject/edit/no-post decisions feed the next decision context; generated output cannot train itself. Reviewer identity is self-reported in this local-only app.
- Machine pass, human editorial approval and actual publication remain separate states.

## Planned files

- `live/account_intelligence.py`: contracts, immutable store, temporal account state, review/publication/feedback and human-only export.
- `live/account_intelligence_pipeline.py`, `live/account_intelligence_prompts.py`: research extraction, event decision, candidates and QA.
- `live/owned_accounts.json`: five owned-account charters (bootstrap editorial hypotheses, not learned profiles).
- `scripts/run_account_intelligence.py`: import/replay/run/export CLI, existing relay logging/budget.
- `backend/account_intelligence.py`, `frontend/account-intelligence.*`: local review surface integrated with existing server.
- `tests/test_account_intelligence.py`: meaningful contract and API regressions.
- `runs/account_intelligence_v1/`: immutable inputs, real call logs/results, human-review packet and integrity report.

## Explicit limits and later milestones

This delivery implements the end-to-end local review loop and runs it on real stored material. It does not pretend the following inputs already exist:

- Human-adopted worldview and preferred-post labels: UI and persistence are implemented; the user supplies actual judgments. No agent-generated “human” labels.
- Complete historical context: selectively reconstructed primary captures are dated and labeled; unknown triggers, price moves and archive gaps remain unknown. Broader reconstruction is a separately measurable data project.
- Current daily coverage: the opt-in CLI accepts freshly captured events and news candidates; no scheduler or production switch is enabled. Missing current evidence is a hold, not a generated market claim.
- Platform bindings and publishing: five logical accounts only; record publication links, never publish automatically.
- Fine-tuning: no LoRA/DPO. First gather event/account decisions and candidate preferences, chronologically split by event/source family, compare retrieval baseline and review repeated failures. Training only after that evidence demonstrates a need.
- Automatic performance optimization: expose feedback and retrieve actual human preferences; do not infer quality or causality from sparse engagement.

## Completion report

Report files changed, actual new data flow, tests, exact pilot outputs and stops, separate machine/human results, remaining stubs or data dependencies, and intentionally unimplemented audit items. Do not call infrastructure completion account-quality acceptance.

Execution evidence: `runs/account_intelligence_v1/DELIVERY.md`, `tests.json`, `case_matrix.json`, `integrity.json`, and `review/FOUR_FIXTURES.md`. All six implementation steps are connected in the opt-in desk. The human-dependent and historical-data milestones above are deliberately not marked complete. The first replay produced 18 drafts, one composite machine fidelity pass, zero human acceptance labels and zero adopted account beliefs.
