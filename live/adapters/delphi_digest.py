"""Delphi Digital (members-only) -> inspiration-only units from a browser-written digest (Oct 7, fd20).

There is NO automated access to Delphi: no scraping, no cookies, no CDP. A separate browser routine, run by a
person in their own logged-in browser, writes one file per day:

    live/store/delphi_digest/<YYYY-MM-DD>.json   (a JSON list; schema in docs/DELPHI_DIGEST.md)

    {"title", "url", "date", "kind": "report"|"alpha_insight", "tickers": [..],
     "thesis_summary": "<our own words>", "key_numbers": [{"value": "...", "context": "..."}]}

This adapter only reads and validates those files. Licence (live/source_licence.json delphi_digital):
inspiration_only (tier C). The units never enter the content store (it only takes tier A/B), never reach a writer
prompt, and may only steer topic selection (scripts/daily_compose.py ranks packs on the same tickers first) and
stance. live/licence_rules.inspiration_findings HOLDs any draft that cites Delphi, reuses its title wording, or
uses one of its key numbers that no public (tier A/B) unit in the draft's pack also gives.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIGEST_DIR = ROOT / 'live' / 'store' / 'delphi_digest'
SOURCE_ID = 'delphi_digital'
PUBLISHER = 'Delphi Digital'
ADAPTER = 'browser_digest'
KINDS = ('report', 'alpha_insight')
LICENCE = 'inspiration_only'
FIELDS = ('title', 'url', 'date', 'kind', 'tickers', 'thesis_summary', 'key_numbers')
STEER_DAYS = 7
_DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_TICKER = re.compile(r'^\$?[A-Z0-9][A-Z0-9.\-]{0,14}$')
_QUOTED = re.compile(r'“[^”]{12,}”|"[^"\n]{12,}"|「[^」]{6,}」')
_DIGIT = re.compile(r'\d')


def _str(v):
    return isinstance(v, str) and bool(v.strip())


def validate_item(item):
    """List of error strings for one digest entry (empty = valid)."""
    if not isinstance(item, dict):
        return ['entry is not an object']
    errors = [f'missing {k}' for k in FIELDS if k not in item]
    extra = set(item) - set(FIELDS)
    if extra:
        errors.append(f'unknown fields {sorted(extra)} (only {list(FIELDS)}; never paste Delphi text)')
    if 'title' in item and not _str(item['title']):
        errors.append('title must be a non-empty string')
    if 'url' in item and not (_str(item['url']) and item['url'].startswith('https://')):
        errors.append('url must be an https URL')
    if 'date' in item:
        try:
            ok = _str(item['date']) and _DAY.match(item['date']) and date.fromisoformat(item['date'])
        except ValueError:
            ok = False
        if not ok:
            errors.append('date must be YYYY-MM-DD')
    if 'kind' in item and item['kind'] not in KINDS:
        errors.append(f'kind must be one of {list(KINDS)}')
    if 'tickers' in item:
        t = item['tickers']
        if not isinstance(t, list) or any(not isinstance(x, str) or not _TICKER.match(x.strip()) for x in t):
            errors.append('tickers must be a list of upper-case symbols (e.g. "ETH", "HYPE", "COIN")')
    if 'thesis_summary' in item:
        s = item['thesis_summary']
        if not _str(s) or len(s.strip()) < 20:
            errors.append('thesis_summary must be >= 20 characters in our own words')
        elif _QUOTED.search(s):
            errors.append('thesis_summary contains a quoted passage; paraphrase in our own words, no quotes')
    if 'key_numbers' in item:
        nums = item['key_numbers']
        if not isinstance(nums, list):
            errors.append('key_numbers must be a list')
        else:
            for i, n in enumerate(nums):
                if not isinstance(n, dict) or set(n) != {'value', 'context'}:
                    errors.append(f'key_numbers[{i}] must be {{"value", "context"}}')
                elif not (_str(n['value']) and _DIGIT.search(n['value'])):
                    errors.append(f'key_numbers[{i}].value must contain a number')
                elif not _str(n['context']) or len(n['context'].strip()) < 8:
                    errors.append(f'key_numbers[{i}].context must say what the number measures')
    return errors


def validate(payload):
    """{'ok', 'items', 'errors': [{'index', 'title', 'errors'}]} for one day's file content."""
    if not isinstance(payload, list):
        return {'ok': False, 'items': 0, 'errors': [{'index': None, 'title': None, 'errors': ['file must be a JSON list']}]}
    errors = []
    for i, item in enumerate(payload):
        e = validate_item(item)
        if e:
            errors.append({'index': i, 'title': (item or {}).get('title') if isinstance(item, dict) else None, 'errors': e})
    return {'ok': not errors, 'items': len(payload), 'errors': errors}


def to_unit(item, day=None):
    from live.adapters.common import digest
    return {'unit_id': 'delphi-' + digest(item['url'] + '|' + item['date'])[:16], 'source_id': SOURCE_ID,
            'publisher': PUBLISHER, 'adapter': ADAPTER, 'digest_day': day,
            'licence': LICENCE, 'licence_tier': 'C', 'usage': LICENCE, 'quote_allowed': False,
            'numbers_allowed': False, 'citable': False,
            'title': item['title'].strip(), 'url': item['url'].strip(), 'date': item['date'], 'kind': item['kind'],
            'tickers': sorted({t.strip().lstrip('$').upper() for t in item['tickers']}),
            'thesis_summary': item['thesis_summary'].strip(),
            'key_numbers': [{'value': n['value'].strip(), 'context': n['context'].strip()} for n in item['key_numbers']]}


def load_day(day, directory=None):
    """{'day', 'status', 'units', 'errors'}: invalid entries are reported and skipped, never half-used."""
    day = day.isoformat() if isinstance(day, date) else str(day)
    path = Path(directory or DIGEST_DIR) / f'{day}.json'
    if not path.exists():
        return {'day': day, 'status': 'missing', 'units': [], 'errors': []}
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return {'day': day, 'status': 'invalid_json', 'units': [], 'errors': [str(exc)]}
    report = validate(payload)
    if not isinstance(payload, list):
        return {'day': day, 'status': 'invalid', 'units': [], 'errors': report['errors']}
    bad = {e['index'] for e in report['errors']}
    units = [to_unit(item, day) for i, item in enumerate(payload) if i not in bad]
    return {'day': day, 'status': 'ok' if not bad else 'partial', 'units': units, 'errors': report['errors']}


def recent(*, now=None, days=STEER_DAYS, directory=None):
    """Valid units from the last `days` digest files (inclusive of today), deduped by unit_id."""
    now = now or datetime.now(timezone.utc)
    if isinstance(now, str):   # compose passes ISO strings
        now = datetime.fromisoformat(now.replace('Z', '+00:00')) if 'T' in now else date.fromisoformat(now[:10])
    today = now.date() if isinstance(now, datetime) else now
    out = {}
    for k in range(days):
        for u in load_day(today - timedelta(days=k), directory)['units']:
            out.setdefault(u['unit_id'], u)
    return list(out.values())


def steer_tickers(units):
    """{ticker: n units} - topic steer only (which packs to look at first), never content."""
    out = {}
    for u in units:
        for t in u['tickers']:
            out[t] = out.get(t, 0) + 1
    return out


def stance_hints(units, tickers):
    """Our own thesis_summary lines for the given tickers (stance steer only). Never key_numbers, never title."""
    want = {t.upper() for t in tickers}
    return [{'tickers': u['tickers'], 'kind': u['kind'], 'thesis_summary': u['thesis_summary']}
            for u in units if want & set(u['tickers'])]


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='Validate a Delphi browser digest file (docs/DELPHI_DIGEST.md).')
    ap.add_argument('path', type=Path)
    args = ap.parse_args(argv)
    try:
        payload = json.loads(args.path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'ok': False, 'error': f'{type(exc).__name__}: {exc}'}))
        return 2
    report = validate(payload)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
