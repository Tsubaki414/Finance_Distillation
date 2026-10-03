"""Explicit, opt-in local commands. No production writes or automatic publishing.

python -m scripts.run_account_intelligence seed
python -m scripts.run_account_intelligence research
python -m scripts.run_account_intelligence run --case F01 --account zh_macro
python -m scripts.run_account_intelligence packet
python -m scripts.run_account_intelligence import-event /path/to/bundle.json
python -m scripts.run_account_intelligence news --limit 10
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

from live.account_intelligence import Store, ROOT, accounts, now, time
from live.account_intelligence_pipeline import Pipeline
from live.distillation_source import digest

RUN = ROOT / 'runs/account_intelligence_v1'


def captured_source(key, text, author, language, published, captured, url, provenance, **extra):
    return {'id': key, 'original_text': text, 'author_name': author, 'author_id': None,
        'publication': author, 'platform': 'web', 'source_language': language,
        'published_at': published, 'fetched_at': captured, 'url': url, 'raw_import_ref': provenance,
        'content_complete': True, 'media_dependencies': [], 'context_status': 'complete_selected_excerpt',
        'post_type': 'primary_document_excerpt', **extra}


def seed(store):
    path = RUN / 'fixtures.json'
    if path.exists():
        return json.loads(path.read_text())
    registry = json.loads((ROOT / 'data/evidence/registry.json').read_text())
    src = next(s for s in registry['sources'] if s['id'] == 'bls-august')
    snapshot = next(s for s in registry['snapshots'] if s['id'] == 'august-release')
    text = '\n'.join(v for k, v in sorted(src['source_lines'].items(), key=lambda kv: int(kv[0])) if 193 <= int(k) <= 292)
    bls = store.source(captured_source('bls-august', text, src['publisher'], 'en', snapshot['published_at'],
        src['observed_at'], src['url'], 'data/evidence/registry.json#august-release'))
    evidence = []
    for fact in snapshot['facts']:
        # Prefer a span containing the complete statistic, not a sentence fragment.
        span = fact['spans'][-1]['text']
        evidence.append({'id': 'bls-' + fact['id'], 'source_id': bls['id'], 'quote': span,
            'claim': f"{fact['id']}: {fact['value']} {fact['unit']}, period {fact['period']}; this release's vintage.",
            'period': fact['period'], 'role': 'primary', 'known_at': src['observed_at']})
    e1 = store.event({'family': 'bls-august-2026', 'title': snapshot['title'], 'mode': 'replay',
        'occurred_at': snapshot['published_at'], 'as_of': '2026-09-06T03:00:00+00:00',
        'source_ids': [bls['id']], 'evidence': evidence, 'market_context': [],
        'coverage': 'Stored primary capture; replay starts after actual local capture, not at release minute. No market reaction/consensus supplied.'})
    npath = ROOT / 'data/finance_supplement/nvidia-primary.web-capture.json'
    capture = json.loads(npath.read_text())
    lines = {int(n): t for n, t in re.findall(r'L(\d+): ([^\n]*)', capture['capture'])}
    ntext = lines[104] + '\n' + lines[105] + '\n\n' + lines[106] + '\n\n' + lines[109]
    url = re.search(r'https://investor\.nvidia\.com/[^)]+', capture['capture']).group()
    nv = store.source(captured_source('nvidia-q2-fy2027-excerpt', ntext, 'NVIDIA Investor Relations', 'en',
        '2026-08-26T23:59:59+00:00', capture['observed_at'], url, str(npath.relative_to(ROOT)),
        publication_time_precision='date_only; end of UTC day used conservatively'))
    ne = [{'id': 'nv-results', 'source_id': nv['id'], 'quote': lines[106], 'claim': 'Reported Q2 FY2027 results.', 'period': 'Q2 FY2027 ended July 26, 2026', 'role': 'primary', 'known_at': capture['observed_at']},
          {'id': 'nv-capital-return', 'source_id': nv['id'], 'quote': lines[109], 'claim': 'Capital returned and remaining authorization are distinct.', 'period': 'Q2 FY2027', 'role': 'primary', 'known_at': capture['observed_at']}]
    e2 = store.event({'family': 'nvidia-q2-fy2027', 'title': 'NVIDIA results and capital allocation — captured excerpt', 'mode': 'replay',
        'occurred_at': nv['published_at'], 'as_of': '2026-09-06T03:00:00+00:00', 'source_ids': [nv['id']],
        'evidence': ne, 'market_context': [], 'coverage': 'Selected source excerpt; no stock price, demand checks or current September outlook.'})
    morris = json.loads((ROOT / 'runs/content_workbench_v1/morris/development_cases.json').read_text())['cases'][0]['source']
    ms = store.source(morris)
    current = now()
    e3 = store.event({'family': 'morris-learning-framework', 'title': 'Evergreen research: finding the right thing through iteration', 'mode': 'evergreen',
        'occurred_at': ms['published_at'], 'as_of': current, 'source_ids': [ms['id']],
        'evidence': [{'id': 'morris-iteration', 'source_id': ms['id'], 'quote': ms['original_text'],
            'claim': 'Historical framework about testing and feedback, not a verified universal causal fact or an account biography.',
            'period': ms['published_at'][:10], 'role': 'historical_framework', 'known_at': ms['known_at']}],
        'coverage': 'Historical framework reactivation; no new market trigger is inferred.'})
    hroot = ROOT / 'runs/content_acceptance_followup_v1/follow_up_results/candidate'
    skip = store.source(json.loads((hroot / 'H08_skip_joke/metadata.json').read_text())['source'])
    e4 = store.event({'family': 'H08_skip_joke-diagnostic', 'title': 'Original H08 off-topic joke — owned-account decision diagnostic',
        'mode': 'evergreen', 'occurred_at': skip['published_at'], 'as_of': current, 'source_ids': [skip['id']],
        'evidence': [{'id': 'joke-source', 'source_id': skip['id'], 'quote': skip['original_text'],
            'claim': 'A social post; no asserted financial event.', 'period': skip['published_at'][:10],
            'role': 'reported_claim', 'known_at': skip['known_at']}], 'coverage': 'Explicit negative suitability case, not an inferred absence.'})
    alab = store.source(json.loads((hroot / 'H03_zh_short_identity/metadata.json').read_text())['source'])
    e5 = store.event({'family': 'H03_zh_short_identity-diagnostic', 'title': 'ALAB historical framework vs personal position',
        'mode': 'current', 'occurred_at': alab['published_at'], 'as_of': current, 'source_ids': [alab['id']],
        'evidence': [], 'blocking_gaps': ['Historical author holding and $50→$1000 assertion lack current company evidence; research extraction may proceed, current ALAB recommendation may not.'],
        'coverage': 'Diagnostic of H03; original failure and follow-up remain immutable. No fabricated current catalyst.'})
    value = {'created_at': current, 'role': 'development_replay_not_holdout', 'cases': [
        {'id': 'F01', 'description': 'English long primary macro source → Chinese macro (also evaluate all other accounts)', 'event_id': e1['id'], 'primary_account': 'zh_macro'},
        {'id': 'F02', 'description': 'English short primary company excerpt → Chinese industry', 'event_id': e2['id'], 'primary_account': 'zh_industry'},
        {'id': 'F03', 'description': 'Chinese short Morris research → English frameworks', 'event_id': e3['id'], 'primary_account': 'en_morris_archive'},
        {'id': 'F04', 'description': 'Original H08 skip source → no account should force a financial post', 'event_id': e4['id'], 'primary_account': None},
        {'id': 'D01', 'description': 'Original H03 ALAB diagnostic: research units plus current-evidence hold', 'event_id': e5['id'], 'primary_account': 'en_industry', 'original_identity': 'H03_zh_short_identity'}],
        'research_source_ids': [ms['id'], alab['id']]}
    RUN.mkdir(exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    return value


def import_bundle(store, path):
    bundle = json.loads(Path(path).read_text())
    remap = {source['id']: store.source(source)['id'] for source in bundle['sources']}
    event = bundle['event']
    event['source_ids'] = [remap[sid] for sid in event['source_ids']]
    event['research_source_ids'] = [remap.get(sid, sid) for sid in event.get('research_source_ids', [])]
    for evidence in event.get('evidence', []):
        evidence['source_id'] = remap[evidence['source_id']]
    return store.event(event)


def import_news(store, limit):
    """Real feed candidates, not fabricated full-text evidence. Enrichment is explicit."""
    records = [json.loads(line) for line in (ROOT / 'live/store/news.jsonl').read_text().split('\n') if line.strip()]
    result = []
    for row in records[-limit:]:
        if not row.get('published_at') or not row.get('first_seen_at'):
            continue
        src = store.source(captured_source(row['item_id'], row['title'] + '\n\n' + row.get('summary', ''),
            row['source'], row.get('lang'), row['published_at'], row['first_seen_at'], row['url'],
            'live/store/news.jsonl#' + row['item_id'], content_complete=False, post_type='rss_excerpt'))
        result.append(store.event({'family': 'news-' + row['item_id'], 'title': row['title'], 'mode': 'current',
            'occurred_at': row['published_at'], 'as_of': now(), 'source_ids': [src['id']], 'evidence': [],
            'blocking_gaps': ['RSS discovery only: recover relevant body/context and admit dated evidence before commentary.'],
            'coverage': 'Existing feed collection; not a verified event fact packet.'}))
    return result


def packet(store):
    destination = RUN / 'review'
    destination.mkdir(parents=True, exist_ok=True)
    runs = store.rows('runs')
    lines = ['# Owned-account review packet', '', 'Real development replays. Machine QA is private; all editorial decisions await actual human review. Historical captures are not current market validation.', '']
    blind = ['# Candidate text review', '', 'Rate naturalness, useful examples/reasoning, rhythm, account fit and angle value. No automatic fidelity score is shown here.', '']
    key = []
    count = 0
    for run in runs:
        decision = run.get('decision', {})
        lines += [f"## {run['event']['title']} · {run['account_id']}", '',
            f"Run `{run['id']}` · as-of {run['event']['as_of']} · {run['status']} · cold start: {run['state']['cold_start']}", '',
            f"Decision: {decision.get('action', 'failed')} — {decision.get('reason', run.get('contract_error', run.get('error_type', '')))}", '',
            'Evidence: ' + ', '.join(e['id'] for e in run['event'].get('evidence', [])), '']
        for candidate in run['candidates']:
            count += 1
            label = f'R{count:03}'
            lines += [f"### {label} · machine fidelity: {candidate.get('machine_fidelity_pass', False)} · human: pending", '', candidate['text'], '']
            blind += [f"## {label} · {account_name(run['account_id'])}", '', candidate['text'], '']
            key.append({'label': label, 'run_id': run['id'], 'candidate_id': candidate['id']})
    (destination / 'FULL_OUTPUTS.md').write_text('\n'.join(lines))
    (destination / 'BLIND_COPY.md').write_text('\n'.join(blind))
    (destination / 'private_key.json').write_text(json.dumps(key, indent=2))
    (destination / 'machine_results.json').write_text(json.dumps(runs, ensure_ascii=False, indent=2))
    export = store.learning_export()
    (destination / 'human_labels.json').write_text(json.dumps(export, ensure_ascii=False, indent=2))
    summary = {'runs': len(runs), 'drafts': count, 'machine_pass': sum(c.get('machine_fidelity_pass', False) for r in runs for c in r['candidates']),
        'statuses': {status: sum(r['status'] == status for r in runs) for status in sorted({r['status'] for r in runs})},
        'human_reviews': len(store.rows('reviews')), 'training_rows': len(export['rows']), 'publishing_enabled': False}
    (RUN / 'results.json').write_text(json.dumps(summary, indent=2))
    return summary


def account_name(key):
    return next(a['name'] for a in accounts() if a['id'] == key)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('command', choices=['seed', 'research', 'run', 'packet', 'import-event', 'news'])
    parser.add_argument('path', nargs='?')
    parser.add_argument('--case')
    parser.add_argument('--account')
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--follow-up-of')
    args = parser.parse_args()
    if args.command == 'run':
        parser.error('Event-first generation retired. Use scripts.run_account_sources with an explicit account and admitted inbox candidate.')
    store = Store()
    if args.command == 'import-event':
        print(json.dumps({'event_id': import_bundle(store, args.path)['id']})); return
    if args.command == 'news':
        print(json.dumps({'event_ids': [r['id'] for r in import_news(store, max(1, min(args.limit, 20)))]})); return
    if args.command == 'packet':
        print(json.dumps(packet(store))); return
    fixtures = seed(store)
    if args.command == 'seed':
        print(json.dumps(fixtures, ensure_ascii=False)); return
    pipeline = Pipeline(store)
    if args.command == 'research':
        for sid in fixtures['research_source_ids']:
            row = pipeline.research(sid)
            print(json.dumps({'source_id': sid, 'research_id': row['id'], 'units': len(row['units'])}), flush=True)
        return
    for case in fixtures['cases']:
        if args.case and args.case != case['id']:
            continue
        for a in accounts():
            if args.account and args.account != a['id']:
                continue
            existing = [r for r in store.rows('runs') if r['event']['id'] == case['event_id'] and r['account_id'] == a['id']]
            if existing and not args.follow_up_of:
                print(json.dumps({'case': case['id'], 'account': a['id'], 'existing_run': existing[-1]['id']}), flush=True); continue
            row = pipeline.run(case['event_id'], a['id'], args.follow_up_of)
            print(json.dumps({'case': case['id'], 'account': a['id'], 'run_id': row['id'], 'status': row['status'], 'error': row.get('contract_error')}), flush=True)


if __name__ == '__main__':
    main()
