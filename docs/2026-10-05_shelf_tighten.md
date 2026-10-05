# Shelf life tighten — 2026-10-05

Fiona: previous shelves felt too long. Applied suggested tier:

| class | was | now |
|---|---|---|
| market_flow | 2 business days | **1 business day** |
| macro_release | 7 calendar days | **3** |
| commentary | 14 | **5** |
| filings_research | 21 | **10** |
| evergreen | none | unchanged |

Breaking still capped at min(shelf, 2). Tests in `tests/test_freshness.py` updated.
