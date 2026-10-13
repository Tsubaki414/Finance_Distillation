# FREEZE / change log (fd-phase0)

## 2026-10-13 01:50 London — Fiona-approved small changes before the 10-13 recompose
Reason: subrouter + micuapi out of credit (HTTP 402) on the 10-12 23:13 nightly; 0 drafts for Beijing 10-13.
Fiona wants no tokens wasted on drafts that a later gate holds, and depth from the source's own analysis.

- Provider: no code change. `FD_GEMINI_PROVIDER=official` + `GEMINI_API_KEY` (~/.secrets/gemini.env, chmod 600)
  routes every Gemini stage to generativelanguage.googleapis.com (native generateContent, existing route).
  Models unchanged (gemini-3-flash-preview / gemini-3.1-pro-preview, both listed by official /models).
  Cost ledgered at official list rates from live/stage_models.json (flash $0.50/$3.00, 3.1-pro $2/$12 per 1M);
  official calls count toward the cap. Subrouter fallback not wired: it has no credit.
- live/opener_mix.fix_opener: EN ngl/idk/tbh opener stripped at the final opener step (after humanize).
- live/one_per_story.cap_plan (FD_STORY_CAP_SELECT, default on): one story across accounts at SELECTION time
  (URL/source key + day motif keys; today's ready rows lock first); analysis sources ranked before flash/headline
  sources within an account.
- live/depth_check.py (FD_DEPTH_CHECK, default on): compose prompt asks for at least one of the SOURCE's own
  insights (reasoning / comparison / affected / what to watch), never invented; deterministic post-check holds a
  pure headline relay (needs_review). Archive / 回看 rows exempt.
- tests/test_oct13_gates.py; tests/test_compose_recorded.py pins FD_DEPTH_CHECK=0 (recorded prompt).
Backup of the pre-change files: /workspace/x/backups/code_<stamp>/.
