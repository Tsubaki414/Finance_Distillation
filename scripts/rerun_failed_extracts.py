"""Retry eligible failed EXTRACT sources once, with per-run budget ledgers.

Malformed JSON retries use two paragraph-aligned halves. All output passes the
unchanged EXTRACT contract and the runner's shared semantic tag/store path.
"""
import argparse
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live import content_store, content_units, jev_front, registry
from scripts.run_content_adapters import ingest_batches
from ml import budget


def split_source(source):
    from live.distillation_source import digest
    text = source['original_text']
    import re
    boundaries = list(re.finditer(r'\n\s*\n', text))
    if not boundaries:
        raise ValueError('Cannot split source without a paragraph boundary')
    split = min(boundaries, key=lambda m: abs(m.start() - len(text)/2))
    chunks = [text[:split.start()], text[split.end():]]
    return [dict(source, id=source['id']+'-'+suffix, original_text=chunk,
                 source_hash=digest(chunk), retry_parent_id=source['id'])
            for suffix, chunk in zip(('a', 'b'), chunks)]


def json_decode_failure(error):
    error = str(error).casefold()
    return error.startswith('contracterror:') and any(token in error for token in
        ('jsondecodeerror', 'json decode', 'malformed json', 'expecting value', 'expecting property name',
         "expecting ',' delimiter", "expecting ':' delimiter", 'unterminated string', 'invalid control character',
         'extra data', 'invalid json', 'incomplete/unknown finish_reason'))


def retry_run(run, store, *, cap_usd=6.0, jev=None, client=None):
    if not math.isfinite(cap_usd) or cap_usd <= 0:
        raise ValueError('cap_usd must be positive and finite')
    run = Path(run)
    budget.STORE = run / 'ledger'
    budget.LEDGER = budget.STORE / 'spend.json'
    budget.DISTILLATION_RUNS = budget.STORE / 'distillation_spend.jsonl'
    budget.RUNS = budget.STORE / 'review_runs.jsonl'
    prior = json.loads(budget.LEDGER.read_text()).get('spent_usd', 0.0) if budget.LEDGER.exists() else 0.0
    budget.set_cap(float(prior) + cap_usd)  # cap_usd is additional budget for this retry
    report = json.loads((run/'report.json').read_text())
    saved = json.loads((run/'sources.json').read_text())
    sources = {s['id']: s for s in saved['text']}
    journal = run / 'rerun_report.json'
    results = json.loads(journal.read_text()) if journal.exists() else {}
    for entry in report['sources']:
        sid = entry['id']; error = entry.get('error', '')
        previous = results.get(sid)
        budget_only = previous is not None and previous.get('attempts') and all(
            str(a.get('error', '')).startswith('BudgetExceeded:') for a in previous['attempts'])
        if entry.get('status') != 'extract_failed' or (previous is not None and not budget_only):
            continue
        if not (json_decode_failure(error) or error.startswith('BudgetExceeded:')):
            continue
        source = sources[sid]
        tier = registry.source_licence_tier(source['source_id'])
        if tier not in ('A', 'B'):
            continue
        results[sid] = {'status': 'retry_started', 'attempts': []}
        journal.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        try:
            parts = split_source(source) if json_decode_failure(error) else [source]
        except ValueError as exc:
            results[sid].update(status='retry_failed', error=str(exc))
            journal.write_text(json.dumps(results, ensure_ascii=False, indent=2)); continue
        batches = []
        for part in parts:
            attempt = {'id': part['id']}
            try:
                if client is None:
                    from live.erisedai_distillation_client import ErisedaiClient
                    client = ErisedaiClient(run/'retry_extract_calls')
                out = content_units.extract(part, client, licence_tier=tier, publisher=part['publisher'])
                (run/f'units_{part["id"]}.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
                batches.append((part, out['units'], part['adapter']))
                attempt.update(status='extracted', units=len(out['units']), dropped=len(out['dropped_units']))
            except Exception as exc:
                attempt.update(status='extract_failed', error=f'{type(exc).__name__}: {str(exc)[:200]}')
            results[sid]['attempts'].append(attempt)
            journal.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        routing = jev_front.route_sources([{'id': s['id'], 'title': s.get('title', ''),
                        'publisher': s.get('publisher'), 'snippet': s['original_text'][:400]} for s, _, _ in batches], jev=jev)
        stored = ingest_batches(store, batches, routing, jev=jev)
        results[sid].update(status='retried', stored=stored, sources=parts)
        journal.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', type=Path, action='append', required=True)
    ap.add_argument('--store', type=Path, required=True)
    ap.add_argument('--jev', action='store_true')
    ap.add_argument('--cap-usd', type=float, default=6.0)
    args = ap.parse_args()
    store = content_store.ContentStore(args.store)
    for run in args.run:
        jev = None
        if args.jev:
            from live.jev_review_client import JevReviewClient
            jev = JevReviewClient(run/'retry_jev_calls')
        results = retry_run(run, store, cap_usd=args.cap_usd, jev=jev)
        print(json.dumps({'run': str(run), 'results': results}, ensure_ascii=False))

if __name__ == '__main__': main()
