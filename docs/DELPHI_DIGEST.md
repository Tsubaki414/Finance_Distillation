# Delphi Digital browser digest (inspiration_only)

Delphi Digital is members-only. **No automated access**: no scraping, no cookies, no CDP, no headless login.
A separate browser routine, run by a person in their own logged-in browser, writes one file per day. The
pipeline only reads that file (`live/adapters/delphi_digest.py`, registry id `delphi_digital`, adapter
`browser_digest`).

## File

`live/store/delphi_digest/<YYYY-MM-DD>.json` (local, ignored by git): a JSON **list** of entries.

| field | type | rule |
|---|---|---|
| `title` | string | the piece's title (used only to block reuse of its wording in drafts) |
| `url` | string | `https://` link to the piece |
| `date` | string | `YYYY-MM-DD`, the piece's publication date |
| `kind` | string | `report` or `alpha_insight` |
| `tickers` | list of strings | upper-case symbols, e.g. `["ETH", "HYPE", "COIN"]` (`$` prefix allowed) |
| `thesis_summary` | string | **our own words**, >= 20 chars, no quoted passages |
| `key_numbers` | list | each `{"value": "62%", "context": "what it measures, period"}`; value contains a number, context >= 8 chars |

No other fields are allowed (no body, excerpt, chart or image fields). Invalid entries are reported and
skipped; valid entries in the same file are still used.

Validate a file:

```
/workspace/fd_venv/bin/python -m live.adapters.delphi_digest live/store/delphi_digest/2026-10-07.json
```

exit 0 = valid, 1 = entry errors (listed), 2 = unreadable / not JSON.

Sample: `docs/samples/delphi_digest_sample.json` (made-up figures, labelled SAMPLE ONLY). Validation on
2026-10-07: `{"ok": true, "items": 2, "errors": []}`. A bad entry (http URL, `10/07` date, kind `note`,
lower-case ticker, quoted passage in the summary, a number without context, an extra `body` field) is
rejected with one message per problem (`tests/test_research_sources.py`).

## Licence: inspiration_only

`live/source_licence.json` `delphi_digital`: tier C, `licence: inspiration_only`, `quote_allowed: false`,
`citable: false`.

- Units never enter the content store (it takes tier A/B only) and are never put in any model prompt.
- Topic steer: `scripts/daily_compose.candidates()` breaks ties toward packs that name a ticker of the newest
  digest written within the last 36h (`delphi_digest.latest`; age from 00:00 London of the file's date, no exact
  day match, so the 04:46 London file steers the 23:13 London run for the next Beijing day; a file dated one day
  ahead also counts). Pack content always comes from public units. The draft gate below still checks the last
  7 days of digests (`delphi_digest.recent`).
- Stance steer: `delphi_digest.stance_hints()` returns only our `thesis_summary` lines for given tickers (never
  numbers or titles). It is not wired into the STANCE prompt yet.
- Draft gate, `live/licence_rules.inspiration_findings`, run in `compose.post_checks` (all HARD -> one targeted
  rewrite, then HOLD):
  - `inspiration_only_cited`: the body names Delphi Digital / Delphi;
  - `inspiration_only_text`: the body reuses >= 5 consecutive words of a digest title;
  - `inspiration_only_number`: a body number equals (or is a rounding of) a digest key number and no public
    (tier A/B) unit span, unit number or source text in the draft's pack gives the same number. The finding
    detail names only the body's own figure, so the rewrite note carries no digest data.
- Charts: drafts only carry charts rendered from our own fetched market data (`live/charts.py`); Delphi charts
  are never stored.
