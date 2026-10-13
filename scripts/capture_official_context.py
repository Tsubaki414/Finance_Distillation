"""Oct 13 (FREEZE.md): nightly capture of official fact-check context (context_only sources: USTR, MOFCOM, Fed, ...)
for the listed accounts, run by scripts/cron/daily_ingest.sh before the ingest. No model calls, no candidates:
rows go to ContextStore (runs/account_sources_v1/store/source_context.sqlite3), cursors to
<store>/official_context_cursors.json. Non-fatal per source. --dry prints counts and writes nothing."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.account_intelligence import DEFAULT
from live.account_sources import universes, registry
from live.source_context import ContextStore, collect_official, is_context_source
from live.distillation_source import now


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--accounts', nargs='+', default=['zh_macro', 'en_macro'])
    ap.add_argument('--store', type=Path, default=DEFAULT)
    ap.add_argument('--limit', type=int, default=3)
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    cat, moment = registry(), now()
    cur_path = a.store / 'official_context_cursors.json'
    cursors = json.loads(cur_path.read_text()) if cur_path.exists() else {}
    report = []
    # The confirmed universe file is the scope (fd20 accounts are not 'enabled' in the old source desk).
    own = {u['account_id']: u for u in universes()}
    loader = lambda aid: own[aid]
    for aid in a.accounts:
        if aid not in own:
            report.append({'account': aid, 'error': 'no confirmed source universe'}); continue
        for sub in own[aid]['subscriptions']:
            sid, cfg = sub['source_id'], cat.get(sub['source_id'], {})
            if not sub.get('enabled') or not is_context_source(sid, cfg) or cfg.get('adapter') != 'official' or cfg.get('enabled') is False:
                continue
            key = aid + ':' + sid
            try:
                rows, cursor, complete, diag = collect_official(aid, sid, cfg, cursors.get(key, {}), moment, a.limit,
                                                                a.store.parent / 'source_captures')
                counts = {} if a.dry or not rows else ContextStore(a.store, universe_loader=loader).record(aid, sid, rows, moment)
                if not a.dry:
                    cursors[key] = cursor
                report.append({'account': aid, 'source': sid, 'listed': diag.get('source_rows'), 'captured': len(rows),
                               'stored': counts, 'failures': len(diag.get('failures') or []),
                               'titles': [r.get('title', '')[:80] for r in rows]})
            except Exception as exc:
                report.append({'account': aid, 'source': sid, 'error': f'{type(exc).__name__}: {str(exc)[:120]}'})
    if not a.dry:
        a.store.mkdir(parents=True, exist_ok=True)
        cur_path.write_text(json.dumps(cursors, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
