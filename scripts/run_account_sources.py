"""Explicit account-source intake and adaptation. No production or publishing."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from live.account_intelligence import Store, ROOT, accounts, now
from live.account_sources import SourcePipeline, ingest, inbox, refresh, universes

RUN = ROOT / 'runs/account_sources_v1'


def seed(store):
    original = json.loads((ROOT / 'runs/account_intelligence_v1/fixtures.json').read_text())
    results = []
    for fixture in original['cases']:
        if fixture['id'] == 'D01':
            continue  # Inactive English industry is preserved in history, not reassigned.
        event = store.get('events', fixture['event_id'])
        source = store.get('sources', event['source_ids'][0])
        account_id = fixture['primary_account'] or 'en_morris_archive'
        result = ingest(store, account_id, source, event_id=event['id'], fixture_id=fixture['id'], batch_id='four-fixtures-v1')
        parents = [r for r in store.rows('runs') if r.get('pipeline') != 'account_source'
                   and r['event']['family'] == event['family'] and r['account_id'] == account_id]
        results.append({'fixture_id': fixture['id'], 'original_event_id': event['id'],
            'account_id': account_id, 'original_source_id': source['id'],
            'follow_up_of': parents[-1]['id'] if parents else None, **result})
    value = {'created_at': now(), 'batch_id': 'four-fixtures-v1', 'cases': results,
             'note': 'Original fixture/source identities retained. Out-of-universe source terminates before LLM. No event broadcast.'}
    path = RUN / 'fixtures.json'
    if not path.exists():
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    return json.loads(path.read_text())


def packet(store, output_dir=None):
    # Historical packets are evidence, not a mutable "latest" report. Every
    # export gets a fresh directory; an explicit existing destination is refused.
    folder = Path(output_dir) if output_dir else RUN / 'review_exports' / now().replace(':', '-')
    folder.mkdir(parents=True, exist_ok=False)
    fixtures_path = RUN / 'fixtures.json'
    fixtures = json.loads(fixtures_path.read_text())['cases'] if fixtures_path.exists() else []
    lines = ['# 四个原始 fixture 的 account-first follow-up', '',
             '开发回放；不是今日行情。机器保真与人工编辑质量分别记录。原文和成稿均为精确保存文本。', '']
    all_runs = [r for r in store.rows('runs') if r.get('pipeline') == 'account_source']
    outputs = []
    for fixture in fixtures:
        sid = fixture.get('original_source_id') or store.get('events', fixture['original_event_id'])['source_ids'][0]
        source = store.get('sources', sid)
        related = [r for r in all_runs if r.get('fixture_id') == fixture['fixture_id']]
        run = related[-1] if related else None
        title = fixture['fixture_id'] + ' · ' + fixture['account_id']
        lines += ['## ' + title, '', 'Original source: ' + (source.get('url') or sid), '',
                  '### 原文', '', source['original_text'], '']
        if run:
            result = run.get('source_adaptation', {})
            passages = (result.get('selection') or {}).get('passages', [])
            lines += ['### 选中原文', '', '\n\n'.join(p['exact_text'] for p in passages) or '未进入选段。', '',
                      '### 翻译 / 同语言原文基线', '', (result.get('translation') or {}).get('text') or '无。', '',
                      '### 成稿', '', '\n\n'.join(c['text'] for c in run['candidates']) or '无成稿。', '',
                      f"机器状态：{run['status']}；人工：pending。", '',
                      '停止/处理状态：' + json.dumps(run.get('decision', {}), ensure_ascii=False), '',
                      'Run: `' + run['id'] + '`; follow-up: `' + str(run.get('follow_up_of')) + '`', '']
        else:
            lines += ['### 成稿', '', '无成稿。' + fixture.get('reason', '尚未执行。'), '', 'LLM / writer 调用：0。', '']
        outputs.append({'fixture': fixture, 'run': run})
    (folder / 'FOUR_FIXTURES.md').write_text('\n'.join(lines))
    (folder / 'exact_outputs.json').write_text(json.dumps(outputs, ensure_ascii=False, indent=2))
    (folder / 'human_quality.json').write_text(json.dumps(store.human_quality(), ensure_ascii=False, indent=2))
    return {'packet': str(folder / 'FOUR_FIXTURES.md'), 'runs': len(all_runs),
            'drafts': sum(len(r['candidates']) for r in all_runs),
            'machine_pass': sum(c['machine_fidelity_pass'] for r in all_runs for c in r['candidates']),
            'human_reviews': sum(v['run_id'] in {r['id'] for r in all_runs} for v in store.rows('reviews')),
            'publishing_enabled': False}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('command', choices=['seed', 'intake', 'inbox', 'refresh', 'run', 'fixtures', 'packet'])
    parser.add_argument('--account')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--candidate')
    parser.add_argument('--follow-up-of')
    parser.add_argument('--limit', type=int, default=3)
    parser.add_argument('--source', action='append', dest='source_ids', help='Refresh only this subscribed source (repeatable)')
    parser.add_argument('--include-x', action='store_true', help='Explicitly allow bounded, metered X collection for this account')
    parser.add_argument('--since', help='X window start YYYY-MM-DD; required with --until')
    parser.add_argument('--until', help='X window exclusive end YYYY-MM-DD; Morris requires an explicit historical window')
    parser.add_argument('--max-sources', type=int, default=3, help='Maximum feed/X/document fetches, 1–12')
    parser.add_argument('--primary-input', type=Path, help='JSON array of subscribed official document source_id/url/published_at')
    parser.add_argument('--current-evidence', type=Path, help='JSON array of explicit source-backed dated verification records; never fetched automatically')
    parser.add_argument('--output', type=Path, help='New directory for packet export; existing directories are never overwritten')
    args = parser.parse_args()
    store = Store()
    RUN.mkdir(exist_ok=True)
    if args.command in ('intake', 'inbox', 'refresh', 'run') and not args.account:
        parser.error('--account is required; there is no all-account default')
    if args.command == 'seed':
        result = seed(store)
    elif args.command == 'inbox':
        result = inbox(store, args.account)
    elif args.command == 'intake':
        if not args.input:
            parser.error('--input JSON source array is required')
        rows = json.loads(args.input.read_text())
        if isinstance(rows, dict):
            rows = rows.get('sources') or [rows]
        result = [ingest(store, args.account, row) for row in rows]
    elif args.command == 'refresh':
        result = refresh(store, args.account, args.limit, source_ids=args.source_ids, include_x=args.include_x,
                         since=args.since, until=args.until, max_sources=args.max_sources,
                         primary_documents=json.loads(args.primary_input.read_text()) if args.primary_input else None)
    elif args.command == 'run':
        if not args.candidate:
            parser.error('--candidate admitted inbox ID is required')
        result = SourcePipeline(store).run(args.account, args.candidate, args.follow_up_of,
                         current_evidence=json.loads(args.current_evidence.read_text()) if args.current_evidence else None)
    elif args.command == 'fixtures':
        result = []
        for fixture in seed(store)['cases']:
            if not fixture['admitted']:
                result.append({'fixture': fixture['fixture_id'], 'status': 'not_admitted', 'model_calls': 0})
                continue
            existing = [r for r in store.rows('runs') if r.get('inbox_candidate_id') == fixture['candidate']['id']]
            run = existing[-1] if existing else SourcePipeline(store).run(fixture['account_id'], fixture['candidate']['id'], fixture['follow_up_of'])
            result.append({'fixture': fixture['fixture_id'], 'run_id': run['id'], 'status': run['status']})
    else:
        result = packet(store, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
