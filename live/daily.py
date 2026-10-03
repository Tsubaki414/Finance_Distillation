"""The daily run. Collect, detect, select, source, write, queue.

This is the loop the product is: it reaches the network every time, and what it produces depends
on what the watched authors were saying in the window it ran over. Run it twice on the same day
and the second run sees engagement that moved, posts that appeared, and a different ranking.

    collect      poll the KOL watchlist on X, append-only
    hotspots     velocity against each author's own baseline, spread, novelty, language gap
    opportunity  score per account; an account with nothing above the floor writes nothing
    resolve      find and fetch the primary document; no document, no piece
    write        each account writes on its own, figures locked to the pack
    queue        distinctness across accounts, then a publish-ready queue

Publishing is not part of this. The queue is where the pipeline ends.

Run: .venv/bin/python -B live/daily.py [--skip-collect] [--floor=6]
"""
from pathlib import Path
import sys, json, datetime, subprocess, re, unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))
STORE = ROOT / 'live/store'


def step(name, fn):
    t0 = datetime.datetime.now()
    print(f'\n[{name}]', flush=True)
    out = fn()
    print(f'  {(datetime.datetime.now() - t0).total_seconds():.0f}s', flush=True)
    return out


def _norm(s):
    return re.sub(r'[^\w一-鿿]+', '', unicodedata.normalize('NFKC', s or '').lower())


def distinctness(drafts):
    """Two accounts must not ship the same event with the same lead claim on the same day.

    The scorer already penalises a crowded entity, but two accounts can still land on one story
    when nothing else clears the floor. That is allowed; shipping the same opening sentence twice
    is not.
    """
    flags = []
    ready = [d for d in drafts if d.get('status') == 'ready_for_queue']
    for i, a in enumerate(ready):
        for b in ready[i + 1:]:
            if a['entity'] != b['entity']:
                continue
            la = _norm((a.get('sentence_to_source_ledger') or [{}])[0].get('text'))
            lb = _norm((b.get('sentence_to_source_ledger') or [{}])[0].get('text'))
            if not la or not lb:
                continue
            overlap = len(set(la) & set(lb)) / max(len(set(la) | set(lb)), 1)
            if overlap > 0.72:
                flags.append({'accounts': [a['account_id'], b['account_id']],
                              'entity': a['entity'], 'lead_overlap': round(overlap, 3),
                              'action': 'held: same event, same lead claim'})
    return flags


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    run_id = 'day-' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S')

    import collect, hotspots, opportunities, resolve_event, write
    cfg = json.loads((ROOT / 'live/accounts.json').read_text())

    ing = None
    if not args.get('skip-collect'):
        # Poll the learning accounts too: 62 handles instead of 12 is most of the English
        # signal coverage, and hotspot spread is counted across distinct authors.
        sys.argv = [sys.argv[0], '--all', '--per=' + str(args.get('per', 12))]
        ing = step('collect', lambda: collect.main())
    hot = step('hotspots', lambda: hotspots.build(48, 336))
    (STORE / 'hotspots.json').write_text(json.dumps(hot, ensure_ascii=False, indent=2))

    def sel():
        picks = opportunities.assign(hot, cfg['accounts'], floor=float(args.get('floor', 6.0)),
                                     per_account=cfg['daily_target']['max'])
        out = {'run_id': run_id, 'accounts': {}, 'nothing_to_say': []}
        for a in cfg['accounts']:
            s = picks.get(a['id'], [])
            out['accounts'][a['id']] = {'name': a['name'], 'lang': a['lang'],
                                        'persona_id': a['persona_id'], 'selected': s,
                                        'selected_count': len(s)}
            if not s:
                out['nothing_to_say'].append(a['id'])
        (STORE / 'opportunities.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
        return out
    opp = step('opportunities', sel)

    def res():
        r = subprocess.run([sys.executable, '-B', str(ROOT / 'live/resolve_event.py')],
                           capture_output=True, text=True, cwd=str(ROOT))
        print(r.stdout.rstrip())
        return r.returncode
    step('resolve', res)

    def gen():
        for f in (STORE / 'drafts').glob('*.json'):
            f.unlink()
        r = subprocess.run([sys.executable, '-B', str(ROOT / 'live/write.py')],
                           capture_output=True, text=True, cwd=str(ROOT),
                           env={**__import__('os').environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        print(r.stdout.rstrip())
        return r.returncode
    step('write', gen)

    drafts = [json.loads(p.read_text()) for p in sorted((STORE / 'drafts').glob('*.json'))]
    held = distinctness(drafts)
    held_ids = {a for h in held for a in h['accounts'][1:]}

    queue = {'run_id': run_id,
             'built_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'window_hours': hot['window_hours'],
             'posts_in_window': hot['posts_in_window'],
             'ingest_run': (ing or {}).get('run_id'),
             'publishing': 'not automated; this queue is the end of the pipeline',
             'accounts': {}, 'distinctness_holds': held}
    for a in cfg['accounts']:
        mine = [d for d in drafts if d['account_id'] == a['id']]
        ready = [d for d in mine if d.get('status') == 'ready_for_queue'
                 and a['id'] not in held_ids]
        queue['accounts'][a['id']] = {
            'name': a['name'], 'lang': a['lang'],
            'selected': opp['accounts'][a['id']]['selected_count'],
            'written': len(mine), 'ready': len(ready),
            'items': [{'draft_id': d['id'], 'entity': d['entity'], 'lane': d['lane'],
                       'title': d.get('title'), 'text': d.get('text'),
                       'primary_url': d['primary_url'], 'source_rank': d['source_rank'],
                       'artifact_sha256': d['artifact_sha256'],
                       'opportunity_score': d['opportunity_score'],
                       'qa_status': d.get('qa_status'),
                       'sentences': len(d.get('sentence_to_source_ledger') or [])}
                      for d in ready],
            'blocked': [{'entity': d['entity'], 'checks': d.get('checks'),
                         'qa_status': d.get('qa_status')}
                        for d in mine if d.get('status') != 'ready_for_queue'],
            'nothing_to_say': a['id'] in opp['nothing_to_say'],
        }
    total = sum(v['ready'] for v in queue['accounts'].values())
    queue['total_ready'] = total
    (STORE / 'queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2))

    print(f"\n=== {run_id} ===")
    print(f"窗口 {hot['window_hours']}h · 窗口内帖子 {hot['posts_in_window']} · "
          f"实体 {len(hot['entities'])} · 加速度可测 {hot['acceleration_available_for']}")
    for aid, v in queue['accounts'].items():
        state = ('今日无够格选题' if v['nothing_to_say'] else
                 f"选题 {v['selected']} · 成稿 {v['written']} · 进队列 {v['ready']}")
        print(f"  {v['name']:<28} {state}")
        for it in v['items']:
            print(f"      · {it['entity']:12} {it['title'][:44]}")
        for b in v['blocked']:
            print(f"      × {b['entity']:12} 被拦：{b['checks']}")
    if held:
        print(f"  跨账号去重扣留：{held}")
    print(f"\n待发布合计 {total} 条 · queue.json 已写出 · 发布动作不在本流程内")
    return queue


if __name__ == '__main__':
    main()
