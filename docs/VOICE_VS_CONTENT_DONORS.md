# Voice donors vs content donors

**Rule: donor exemplars teach voice and structure only. Facts and numbers come only from content units.**

| | Voice donor | Content donor |
|---|---|---|
| What | Real X accounts (`live/donors/roster.json`, cluster per persona) | Licensed sources (`live/source_licence.json`: A quote / B paraphrase + attribution) |
| Enters at | COMPOSE, as `style_exemplars` (`live/exemplars.py`, max 1 post per donor) | EXTRACT -> ContentUnits (spans must be exact substrings) -> COMPOSE |
| May supply | tone, rhythm, hook shape, length, list/thread structure | facts, numbers, periods, named claims, quotes (A only) |
| Must never supply | facts, numbers, names, claims, personal experience, phrases | voice (the persona owns voice) |
| Enforced by | `compose.EXEMPLAR_RULE` in the request; SOFT `exemplar_phrase_copied`; HARD `number_not_in_units` / `period_not_in_units` for any number not in units (incl. one copied from an exemplar) | licence tier gate, span checks, attribution frame (frame names the publisher, e.g. the bank, never an aggregator) |

Topic radar (C/D sources: news headlines, Reddit, Xueqiu, ima) only decides *what* to write; it never produces units.

Tests: `tests/test_donor_exemplars.py::VoiceVsContentRuleTests`, `tests/test_qa_levels.py`, `tests/test_reportgem_daily.py`.

ReportGem daily pull (`scripts/reportgem_daily.py`) is a content donor at tier B by owner decision 2026-10-04: bank-attributed paraphrase only; ratings / price targets are stripped; items with a third-party redistribution watermark or a stale document date are rejected.
