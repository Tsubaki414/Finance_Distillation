#!/usr/bin/env python3
"""EXTRACT model side-by-side on docs already extracted in a real ingest run (Oct 6, Gemini switch).

For each recorded extract call (ingest_runs/<run>/extract_calls/<id>.json) the source is rebuilt from the
recorded paragraphs (same P-ids and text), the recorded baseline response (claude-opus-5) is re-validated
by the existing contract (no new spend), and each candidate model runs the same EXTRACT through
ErisedaiClient on a scratch budget ledger. Metrics per (doc, model): proposed / accepted / dropped units with
reasons, view_error, numbers bound, statement-number traceability (digits in the free-text statement that are
not in the cited spans), speaker attribution (speaker found in the source or its byline), speaker types, real
cost from reported usage x configured rates. Writes JSON + markdown to --out. Nothing is stored.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MICU = 'https://www.micuapi.ai/v1'
# USD per 1M (input, output); Google list prices (micuapi bills at list), opus as configured in the ledger.
RATES = {'gemini-3.1-pro-preview': (2.0, 12.0), 'gemini-3-flash-preview': (0.5, 3.0),
         'gemini-2.5-flash': (0.3, 2.5), 'claude-opus-5': (15.0, 75.0), 'claude-sonnet-5': (3.0, 15.0)}


def rebuild(record):
    payload = json.loads(record['messages'][-1]['content'])
    text = '\n\n'.join(p['text'] for p in payload['paragraphs'])
    from live.distillation_source import digest, paragraphs
    assert [p['exact_text'] for p in paragraphs(text)] == [p['text'] for p in payload['paragraphs']]
    src = dict(payload['source'])
    return dict(id=src.get('source_id'), source_id=src.get('source_id'), title=src.get('title'),
                author_name=src.get('author_name'), published_at=src.get('published_at'),
                original_text=text, source_hash=digest(text)), src.get('publisher')


_NUM = re.compile(r'\d[\d,]*(?:\.\d+)?')


def _digits(s):
    return s.replace(',', '').replace('.', '').lstrip('0') or '0'


def metrics(source, raw_value, units, dropped):
    text = source['original_text']
    src_digits = {_digits(m) for m in _NUM.findall(text)}
    byline = ' '.join(str(source.get(k) or '') for k in ('author_name', 'title'))
    stmt_nums = stmt_untraced = 0
    untraced_examples = []
    attributed = 0
    for u in units:
        spans = ' '.join(s['exact_text'] for s in u['source_spans'])
        span_digits = {_digits(m) for m in _NUM.findall(spans)}
        for m in _NUM.findall(u['statement']):
            if len(_digits(m)) < 2 and m.isdigit() and int(m) < 10:
                continue   # "one", list indices
            stmt_nums += 1
            if _digits(m) not in span_digits and _digits(m) not in src_digits:
                stmt_untraced += 1
                untraced_examples.append(f"{m} in: {u['statement'][:120]}")
        sp = u['speaker'].strip()
        tokens = [t for t in re.split(r"[\s/,()'’\-]+", sp) if len(t) >= 3 or re.search(r'[\u4e00-\u9fff]', t)]
        if sp in text or sp in byline or any(t in text or t in byline for t in tokens):
            attributed += 1
    proposed = len((raw_value or {}).get('units') or [])
    return dict(proposed=proposed, accepted=len(units), dropped=len(dropped),
                drop_reasons=[d['reason'][:140] for d in dropped],
                kinds=dict(Counter(u['kind'] for u in units)),
                views=sum(1 for u in units if u.get('view')), view_errors=sum(1 for u in units if u.get('view_error')),
                numbers_bound=sum(len(u['numbers']) for u in units),
                statement_numbers=stmt_nums, statement_numbers_untraced=stmt_untraced,
                untraced_examples=untraced_examples[:5],
                speakers_in_source=attributed, speaker_types=dict(Counter(u['speaker_type'] for u in units)),
                speakers=sorted({u['speaker'] for u in units})[:12])


def baseline(record, source, tier):
    from live import content_units
    from live.model_json import parse_object
    text = record['transport_output']['choices'][0]['message']['content']
    value = parse_object(text, repair_quotes=True)
    units, dropped = content_units.validate_units_partial(source, value, tier, require_view=True)
    u = record.get('usage') or {}
    pin, pout = RATES[record['model']]
    cost = u.get('prompt_tokens', 0) / 1e6 * pin + u.get('completion_tokens', 0) / 1e6 * pout
    return dict(model=record['model'], status='ok', finish_reason=record['response'].get('finish_reason'),
                prompt_tokens=u.get('prompt_tokens'), completion_tokens=u.get('completion_tokens'),
                reasoning_tokens=None, cost_usd=round(cost, 4), latency_s=record.get('latency_seconds'),
                **metrics(source, value, units, dropped), units=units)


def candidate(model, source, publisher, tier, directory):
    from live import content_units, stage_models
    from live.erisedai_distillation_client import ErisedaiClient, relay_config
    from live.model_json import parse_object
    if model == 'config':   # the shipped stage table as-is (stage_models.json "extract" + its fallback)
        from live.daily_ingest import extract_table
        table = extract_table()
        model = stage_models.for_stage(table, 'extract')['model']
    else:
        table = stage_models.override(stage_models.load(), 'extract', model, base_url=MICU,
                                      api_key_env='GEMINI_RELAY_API_KEY', rates=RATES[model])
    cfg = relay_config(); cfg['stage_models'] = table
    client = ErisedaiClient(directory, configuration=cfg)
    captured = {}

    def spy(stage, messages, max_tokens):
        r = client(stage, messages, max_tokens)
        captured.update(r)
        return r
    t = time.monotonic()
    try:
        out = content_units.extract(source, spy, licence_tier=tier, publisher=publisher)
        status, err = 'ok', None
        units, dropped = out['units'], out['dropped_units']
    except Exception as exc:
        status, err, units, dropped = 'failed', f'{type(exc).__name__}: {str(exc)[:300]}', [], []
    u = captured.get('usage') or {}
    pin, pout = RATES[model]
    cost = (u.get('prompt_tokens') or 0) / 1e6 * pin + (u.get('completion_tokens') or 0) / 1e6 * pout
    try:
        value = parse_object(captured.get('text', ''), repair_quotes=True)
    except Exception:
        value = None
    reasoning = ((u.get('completion_tokens_details') or {}).get('reasoning_tokens'))
    return dict(model=model, status=status, error=err, finish_reason=captured.get('finish_reason'),
                model_fallback=captured.get('model_fallback'), response_model=captured.get('response_model'),
                prompt_tokens=u.get('prompt_tokens'), completion_tokens=u.get('completion_tokens'),
                reasoning_tokens=reasoning, cost_usd=round(cost, 4), latency_s=round(time.monotonic() - t, 1),
                **metrics(source, value, units, dropped), units=units)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--calls', nargs='+', required=True, help='extract call ids (prefix) under --runs')
    ap.add_argument('--runs', default='/workspace/x/ingest_runs')
    ap.add_argument('--models', nargs='+', default=['gemini-3.1-pro-preview', 'gemini-3-flash-preview'])
    ap.add_argument('--out', type=Path, default=Path('/workspace/x/extract_ab_oct6'))
    ap.add_argument('--cap', type=float, default=1.5)
    args = ap.parse_args(argv)
    from ml import budget
    from live import registry
    args.out.mkdir(parents=True, exist_ok=True)
    budget.STORE = args.out / 'ledger'; budget.LEDGER = budget.STORE / 'spend.json'
    budget.DISTILLATION_RUNS = budget.STORE / 'distillation_spend.jsonl'
    budget.STORE.mkdir(parents=True, exist_ok=True)
    if not budget.LEDGER.exists():
        budget.LEDGER.write_text(json.dumps(dict(cap_usd=args.cap, spent_usd=0, calls=0, reservations={})))
    rows = []
    for cid in args.calls:
        path = glob.glob(f'{args.runs}/*/extract_calls/{cid}*.json')[0]
        record = json.loads(Path(path).read_text())
        source, publisher = rebuild(record)
        tier = registry.source_licence_tier(source['source_id']) or 'B'
        doc = dict(call=cid, path=path, source_id=source['source_id'], title=source['title'], tier=tier,
                   chars=len(source['original_text']), results=[baseline(record, source, tier)])
        for model in args.models:
            print(f'[ab] {cid} {source["source_id"]} -> {model}', file=sys.stderr, flush=True)
            doc['results'].append(candidate(model, source, publisher, tier, args.out / 'calls'))
        rows.append(doc)
        (args.out / 'ab.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1) + '\n')
    lines = ['| doc | model | status | units ok/proposed | dropped | view_err | numbers bound | stmt nums untraced | speakers in source | in/out(reason) tok | cost $ |',
             '|---|---|---|---|---|---|---|---|---|---|---|']
    for d in rows:
        for r in d['results']:
            lines.append(f"| {d['source_id']} | {r['model']} | {r['status']} | {r['accepted']}/{r['proposed']} | {r['dropped']} | "
                         f"{r['view_errors']} | {r['numbers_bound']} | {r['statement_numbers_untraced']}/{r['statement_numbers']} | "
                         f"{r['speakers_in_source']}/{r['accepted']} | {r['prompt_tokens']}/{r['completion_tokens']}({r['reasoning_tokens']}) | {r['cost_usd']} |")
    lines.append(f"\nledger spent: {json.loads(budget.LEDGER.read_text())['spent_usd']}")
    (args.out / 'ab.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
