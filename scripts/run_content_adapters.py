"""Run the front-end source adapters live, EXTRACT text sources (relay), route and
pre-screen with Jev (advisory), and write units into the shared content store.

  python scripts/run_content_adapters.py --run /workspace/x/sources_live/2026-10-04 --extract --jev
Resumable: a source whose units file exists in the run dir is not extracted again.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live import content_store, jev_front, registry  # noqa: E402
from live.adapters import bls, cboe, cftc, defillama, edgar, farside, fed, feeds, fred, longform, treasury  # noqa: E402

ODD_LOTS = ('https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/8a94442e-5a74-4fa2-8b8d-ae27003a8d6b/'
            '982f5071-765c-403d-969d-ae27003a8d83/podcast.rss')


def newsletter_feeds():
    rows = json.loads((ROOT / 'live/source_registry.json').read_text())['sources']
    return [r for r in rows if r.get('type') in ('newsletter', 'wechat') and r.get('feed_url')]


def gather(args, report):
    text_sources, data = [], []
    if 'edgar' in args.adapters:
        for t in args.tickers:
            out = edgar.fetch(t, forms=('8-K',), earnings_only=True, limit=1)
            report['adapters'].setdefault('edgar', []).append({'ticker': t, **{k: v for k, v in out.items() if k != 'sources'},
                                                               'sources': [s['id'] for s in out['sources']]})
            text_sources += out['sources']
    if 'fed' in args.adapters:
        for kind, n in (('speech', 2), ('monetary', 1)):
            out = fed.fetch(kind, limit=n)
            report['adapters'].setdefault('fed', []).append({'kind': kind, 'status': out['status'], 'requests': out.get('requests'),
                                                             'sources': [s['id'] for s in out['sources']]})
            text_sources += out['sources']
    if 'bls' in args.adapters:
        out = bls.fetch()
        report['adapters']['bls'] = {k: v for k, v in out.items() if k not in ('sources', 'units')} | {'units': len(out['units'])}
        data += [(s, out['units'], 'bls_api') for s in out['sources']]
    if 'treasury' in args.adapters:
        out = treasury.fetch()
        report['adapters']['treasury'] = {k: v for k, v in out.items() if k not in ('sources', 'units')} | {'units': len(out['units'])}
        data += [(s, out['units'], 'treasury_fiscaldata') for s in out['sources']]
    if 'fred' in args.adapters:
        report['adapters']['fred'] = {k: v for k, v in fred.fetch_series('UNRATE').items() if k not in ('sources', 'units')}
    if 'newsletters' in args.adapters:
        rows, extract_budget = [], args.newsletter_extract
        for f in newsletter_feeds():
            out = feeds.fetch_newsletter(f, limit=1)
            tier = registry.source_licence_tier(f['id'])
            rows.append({'id': f['id'], 'status': out['status'], 'tier': tier, 'full_text': bool(out['sources'])})
            if out['sources'] and tier in ('A', 'B') and extract_budget > 0:
                text_sources += out['sources']
                extract_budget -= 1
        report['adapters']['newsletters'] = rows
    if 'podcasts' in args.adapters:
        out = feeds.fetch_podcast(ODD_LOTS, source_id='podcast_odd_lots', publisher='Bloomberg Odd Lots')
        report['adapters']['podcasts'] = [{'feed': 'Odd Lots', **{k: v for k, v in out.items() if k != 'sources'}}]
        text_sources += out['sources']
    for name, adapter in (('cftc', cftc), ('cboe', cboe), ('farside', farside), ('defillama', defillama)):
        if name in args.adapters:
            out = adapter.fetch()
            report['adapters'][name] = {k: v for k, v in out.items() if k not in ('sources', 'units')} | {'units': len(out['units'])}
            data += [(s, [u for u in out['units'] if u['source_hash'] == s['source_hash']], s['adapter']) for s in out['sources']]
    for name, fetch, options in (('oaktree', longform.fetch_oaktree, {'limit': args.oaktree_n}),
                                ('berkshire', longform.fetch_berkshire, {}),
                                ('glassnode', longform.fetch_glassnode, {'limit': args.glassnode_n})):
        if name in args.adapters:
            out = fetch(**options)
            report['adapters'][name] = {k: v for k, v in out.items() if k != 'sources'} | {'sources': [s['id'] for s in out['sources']]}
            text_sources += out['sources']
    return text_sources, data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', type=Path, required=True)
    ap.add_argument('--store', type=Path, default=None)
    ap.add_argument('--adapters', nargs='+', default=['edgar', 'fed', 'bls', 'treasury', 'fred', 'newsletters', 'podcasts',
                                                    'cftc', 'cboe', 'farside', 'defillama', 'oaktree', 'berkshire', 'glassnode'])
    ap.add_argument('--tickers', nargs='+', default=['MU', 'NVDA'])
    ap.add_argument('--newsletter-extract', type=int, default=3)
    ap.add_argument('--oaktree-n', type=int, default=3)
    ap.add_argument('--glassnode-n', type=int, default=3)
    ap.add_argument('--extract', action='store_true')
    ap.add_argument('--jev', action='store_true')
    args = ap.parse_args()
    args.run.mkdir(parents=True, exist_ok=True)
    from ml import budget as spend
    spend.STORE = args.run / 'ledger'
    spend.LEDGER = spend.STORE / 'spend.json'
    report = {'adapters': {}, 'sources': [], 'ua_placeholder': edgar.user_agent()[1]}
    cached = args.run / 'sources.json'
    if cached.exists():
        saved = json.loads(cached.read_text())
        text_sources, data = saved['text'], [tuple(x) for x in saved['data']]
        report['adapters'] = saved['adapters']
    else:
        text_sources, data = gather(args, report)
        cached.write_text(json.dumps({'text': text_sources, 'data': data, 'adapters': report['adapters']}, ensure_ascii=False))
    jev = None
    if args.jev:
        from live.jev_review_client import JevReviewClient
        jev = JevReviewClient(args.run / 'jev_calls')
    all_sources = text_sources + [s for s, _, _ in data]
    routing = jev_front.route_sources([{'id': s['id'], 'title': s.get('title') or '', 'publisher': s.get('publisher'),
                                        'snippet': s['original_text'][:400]} for s in all_sources], jev=jev)
    store = content_store.ContentStore(args.store)
    client = None
    batches = [(s, units, adapter) for s, units, adapter in data]
    for s in text_sources:
        tier = registry.source_licence_tier(s['source_id'])
        done = args.run / f'units_{s["id"]}.json'
        entry = {'id': s['id'], 'adapter': s['adapter'], 'tier': tier, 'chars': len(s['original_text']),
                 'truncated': s.get('truncated'), 'route': routing.get(s['id'])}
        if tier not in ('A', 'B'):
            entry['status'] = 'no_writable_licence'
        elif done.exists():
            out = json.loads(done.read_text())
            batches.append((s, out['units'], s['adapter']))
            entry.update(status='resumed', units=len(out['units']), dropped=len(out['dropped_units']))
        elif args.extract:
            from live import content_units
            if client is None:
                from live.erisedai_distillation_client import ErisedaiClient
                client = ErisedaiClient(args.run / 'extract_calls')
            try:
                out = content_units.extract(s, client, licence_tier=tier, publisher=s['publisher'])
                done.write_text(json.dumps(out, ensure_ascii=False, indent=1))
                batches.append((s, out['units'], s['adapter']))
                entry.update(status='extracted', units=len(out['units']), dropped=len(out['dropped_units']))
            except Exception as exc:
                entry.update(status='extract_failed', error=f'{type(exc).__name__}: {str(exc)[:200]}')
        else:
            entry['status'] = 'fetched_not_extracted'
        report['sources'].append(entry)
    for s, units, adapter in data:
        report['sources'].append({'id': s['id'], 'adapter': adapter, 'tier': registry.source_licence_tier(s['source_id']),
                                  'status': 'deterministic_units', 'units': len(units), 'route': routing.get(s['id'])})
    stored = {'added': 0, 'duplicate': 0}
    for s, units, adapter in batches:
        persona = (routing.get(s['id']) or {}).get('persona')
        personas = [persona] if persona and persona != 'none' else []
        screen = jev_front.prescreen_units(units, persona=personas[0], jev=jev) if personas and units else {}
        keep = [u for u in units if (screen.get(u['unit_id']) or {}).get('verdict', 'keep') != 'drop']
        r = store.add(s, keep, adapter=adapter, personas={u['unit_id']: personas for u in keep}, prescreen=screen)
        stored['added'] += r['added']
        stored['duplicate'] += r['duplicate']
        stored.setdefault('dropped_by_prescreen', 0)
        stored['dropped_by_prescreen'] += len(units) - len(keep)
    report['stored'] = stored
    report['store_stats'] = store.stats()
    report['jev_calls'] = len(jev.calls) if jev else 0
    report['jev_fallbacks'] = sum(1 for v in routing.values() if v['jev_fallback'])
    (args.run / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps({k: report[k] for k in ('stored', 'store_stats', 'jev_calls', 'jev_fallbacks', 'ua_placeholder')}, indent=1))


if __name__ == '__main__':
    main()
