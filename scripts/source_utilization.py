"""Audit expansion channels and X voice donors against the active content store.

Matching is explicit ID/adapter mapping first, exact publisher identity next,
then URL host (never substring). Channels sharing a host use their URL path.
Newsletter feed hosts also match article URLs on that host.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.content_store import ContentStore

ROOT = Path(__file__).resolve().parents[1]
# Channel labels are matched as prefixes/known labels, not inferred from prose.
CHANNEL_MATCH = {
    'Fed': ('fed_rss', 'primary_fed'),
    'Treasury FiscalData': ('treasury_fiscaldata', 'primary_treasury'),
    'SEC EDGAR': ('edgar', 'sec_edgar'),
    'BLS': ('bls_api', 'primary_bls'),
    'Oaktree': ('oaktree', 'oaktree_memos'),
    'Glassnode': ('glassnode', 'glassnode_research'),
    'SemiAnalysis': ('semianalysis', 'newsletter_semianalysis', 'semianalysis'),
    'ReportGem': ('reportgem',),
    'CFTC': ('cftc', 'primary_cftc'),
    'Cboe': ('cboe', 'cboe_indices'),
    'Farside': ('farside', 'farside_etf_flows'),
    'DefiLlama': ('defillama', 'defillama_stablecoins'),
    'NY Fed': ('nyfed', 'primary_nyfed'),
    '华尔街见闻': ('wallstreetcn',),
    'St. Louis Fed': ('fred', 'fred_api', 'primary_fred'),
    'Odd Lots': ('podcast_odd_lots',),
}
CHANNEL_URL_PATHS = {
    'SEC EDGAR': (('sec.gov', '/Archives/edgar/'), ('data.sec.gov', '/submissions/')),
    'Fed': (('federalreserve.gov', '/newsevents/speech/'),
            ('federalreserve.gov', '/newsevents/pressreleases/monetary'),
            ('federalreserve.gov', '/econres/feds')),
}
CHANNEL_PUBLISHERS = {
    'Fed': ('Federal Reserve', 'Federal Reserve Board'),
    'Treasury FiscalData': ('U.S. Treasury', 'U.S. Department of the Treasury'),
    'BLS': ('U.S. Bureau of Labor Statistics', 'Bureau of Labor Statistics', 'BLS'),
    'Oaktree': ('Oaktree Capital (Howard Marks)', 'Oaktree Capital'),
    'Glassnode': ('Glassnode',), 'SemiAnalysis': ('SemiAnalysis',),
    'CFTC': ('CFTC',), 'Cboe': ('Cboe Global Markets',),
    'Farside': ('Farside Investors',), 'DefiLlama': ('DefiLlama',),
    'NY Fed': ('Federal Reserve Bank of New York',), '华尔街见闻': ('华尔街见闻',),
}
SHARED_HOSTS = {'www.sec.gov', 'sec.gov', 'www.federalreserve.gov', 'federalreserve.gov',
                'feeds.megaphone.fm', 'weixin.sogou.com', 'www.google.com', 'www.omnycontent.com'}


def _host(url):
    return (urlparse(url or '').hostname or '').casefold().removeprefix('www.')


def _ids(channel):
    name = channel.get('name', '')
    return {v for label, values in CHANNEL_MATCH.items() if name.casefold().startswith(label.casefold()) for v in values}


def match_channel(channel, row):
    """True when a stored source/registry row belongs to this channel.

    Explicit mappings take precedence on shared official hosts (EDGAR never
    absorbs SEC press releases). Matching requires at least one identity field.
    """
    source = row.get('source', row)
    if channel.get('channel_id') and source.get('source_id'):
        # Channel IDs are authoritative; legacy adapter IDs retain their explicit mapping.
        if source['source_id'] == channel['channel_id']:
            return True
        if source['source_id'] not in _ids(channel):
            return False
    ids = _ids(channel) | ({channel['channel_id']} if channel.get('channel_id') else set())
    identity = {str(source.get(k) or '').casefold() for k in ('source_id', 'id', 'adapter')}
    if any(i.casefold() in identity or (i == 'reportgem' and any(x.startswith('reportgem_') for x in identity)) for i in ids):
        return True
    publisher = str(source.get('publisher') or '').casefold()
    if publisher and any(publisher == alias.casefold() for label, aliases in CHANNEL_PUBLISHERS.items()
                         if channel.get('name', '').casefold().startswith(label.casefold()) for alias in aliases):
        return True
    name = str(channel.get('name') or '').casefold()
    if name and name in {str(source.get(k) or '').casefold() for k in ('publisher', 'name')}:
        return True
    target = channel.get('url') or channel.get('feed_url') or ''
    url = source.get('url') or source.get('feed_url') or ''
    host = _host(target)
    for label, paths in CHANNEL_URL_PATHS.items():
        if channel.get('name', '').casefold().startswith(label.casefold()):
            if any(_host(url) == domain and urlparse(url).path.startswith(prefix) for domain, prefix in paths):
                return True
    if not host or host != _host(url):
        return False
    if host in {_host('https://'+h) for h in SHARED_HOSTS}:
        # For multi-channel official hosts only an explicit identity or exact
        # endpoint/path is evidence; a common publisher domain is insufficient.
        return bool(urlparse(target).path) and urlparse(target).path == urlparse(url).path
    return True


def _build_rows(channel, registry):
    matches = [r for r in registry.get('sources', []) if r.get('enabled', True) and match_channel(channel, r)]
    if matches:
        return matches
    # Structured adapters may exist without a discovery feed in the registry.
    ids = _ids(channel)
    if 'reportgem' in ids and (ROOT / 'live/reportgem_daily.py').exists():
        return [{'id': 'reportgem', 'adapter': 'reportgem'}]
    for adapter in sorted(ids):
        if (ROOT / 'live/adapters' / (adapter + '.py')).exists():
            return [{'id': next((i for i in ids if i.startswith('primary_')), adapter), 'adapter': adapter}]
    # Oaktree/Glassnode live together, and fed RSS is in fed.py.
    module = {'oaktree': 'longform', 'glassnode': 'longform', 'fed_rss': 'fed', 'treasury_fiscaldata': 'treasury', 'bls_api': 'bls'}
    for adapter, file in module.items():
        if adapter in ids and (ROOT / 'live/adapters' / (file + '.py')).exists():
            return [{'id': next((i for i in ids if i.startswith('primary_')), adapter), 'adapter': adapter}]
    return []


def _score(channel, allows, personas_fed):
    persona = str(channel.get('persona_hint', '')) + str(channel.get('persona', ''))
    gap = 5 if 'zh_us_stock_commentary' in persona or (('美股' in persona or '产业' in persona or '华尔街见闻' in channel.get('name', '')) and '中' in str(channel.get('lang', ''))) else 3 if any(t in persona for t in ('trading_shortterm', 'crypto', '交易', '加密')) else 1
    access = str(channel.get('cost', '')) + str(channel.get('access', ''))
    public = any(t in access.casefold() for t in ('免费', '公开', 'free', 'public'))
    verified = '✅' in str(channel.get('verified', ''))
    return (4 * verified + 3 * public + gap / (1 + personas_fed) + 4 * allows,
            {'verified': verified, 'free_public': public, 'persona_gap_weight': gap, 'paraphrase_allowed': allows})


def audit(expansion, registry, licence, roster, store_dir, donor_tags, *, runs=None, planned=None):
    store = ContentStore(store_dir)
    units = store.units()
    tiers = licence.get('tiers', licence.get('sources', {}))
    channels = []
    outcomes = {}
    for report in runs or []:
        if not isinstance(report, dict):
            report = json.loads(Path(report).read_text())
        for outcome in report.get('adapters', {}).get('channels', []):
            outcomes[outcome.get('channel_id') or outcome.get('id')] = outcome
    for channel in planned if planned is not None else expansion['sources']:
        matched = [r for r in units if match_channel(channel, r)]
        built = _build_rows(channel, registry)
        personas = sorted({p for r in matched for p in r.get('tag_personas', [])})
        tier_ids = ({channel['channel_id']} if channel.get('channel_id') else set()) | set(_ids(channel)) | {r['id'] for r in built}
        if 'reportgem' in tier_ids:
            tier_ids |= {i for i in tiers if i.startswith('reportgem_')}
        allowed = any(tiers.get(i, {}).get('tier') in ('A', 'B') for i in tier_ids)
        policy = str(channel.get('license', '')).casefold()
        if not allowed:
            allowed = any(t in policy for t in ('paraphrase', '只取事实', '注明来源', '注明出处', '只取标题+机构+评级+要点')) and not any(t in policy for t in ('禁止', '仅作选题', '灰色', '高风险'))
        score, factors = _score(channel, allowed, len(personas))
        outcome = outcomes.get(channel.get('channel_id'), {})
        reason = outcome.get('reason') or channel.get('reason') or ('no stored content units' if built else 'no adapter or fetch outcome recorded')
        channels.append({**channel, 'mode': channel.get('mode', 'existing_adapter' if built else 'unknown'),
                         'fetch_outcome': outcome.get('status', 'not_run'), 'reason': reason,
                         'personas': personas, 'status': 'in_use' if matched else 'built_unused' if built else 'not_built',
                         'units': len(matched), 'personas_fed': personas, 'built_ids': [r['id'] for r in built],
                         'score': score, 'score_factors': factors})
    tag_files = {p.stem.casefold(): p for p in Path(donor_tags).glob('*.json*')} if Path(donor_tags).exists() else {}
    donors = []
    records = roster.get('donors', {})
    if isinstance(records, list): records = {r['handle']: r for r in records}
    active = {str(d['handle']).casefold() for c in roster.get('persona_clusters', {}).values() for d in c.get('donors', [])}
    for key, donor in records.items():
        handle = donor.get('handle', key)
        tag = tag_files.get(handle.casefold()) or tag_files.get(key.casefold())
        posts = next((p for p in (Path(donor_tags).parent / 'posts').glob('*')
                      if p.suffix in ('.json', '.jsonl') and p.stem.casefold() in (key.casefold(), handle.casefold())),
                     Path(donor_tags).parent / 'posts' / (key.casefold() + '.jsonl'))
        if not tag and not posts.exists():
            continue
        cluster = donor.get('persona_cluster', 'none')
        used = handle.casefold() in active or (not roster.get('persona_clusters') and cluster != 'none' and donor.get('donor_fit', 'voice') != 'exclude')
        donors.append({'name': handle, 'status': 'in_use' if used else 'built_unused', 'units': 0,
                       'persona_cluster': cluster, 'personas_fed': [cluster] if used else [],
                       'voice_exemplar_used': used, 'tags_exist': bool(tag), 'posts_exist': posts.exists(),
                       'usage': 'voice/exemplar donor only; contributes voice, not content units'})
    return {'channels': channels, 'donors': donors, 'donor_count': len(donors),
            'summary': {'channels': dict(Counter(r['status'] for r in channels)), 'donors': dict(Counter(r['status'] for r in donors))},
            'next_to_build': sorted([r for r in channels if r['status'] == 'not_built'], key=lambda r: (-r['score'], r['name']))}


def markdown(result):
    def cell(v): return str(v).replace('|', '\\|').replace('\n', ' ')
    lines = ['# Source utilization', '', f"Channels: {len(result['channels'])}. X donors with posts/tags: {result['donor_count']}.",
             '', 'Donors contribute voice, not content units. Personas for channels come only from semantic tag_personas.',
             '', '| Status | Channels | X donors |', '|---|---:|---:|']
    for status in ('in_use', 'built_unused', 'not_built'):
        lines.append(f"| {status} | {result['summary']['channels'].get(status, 0)} | {result['summary']['donors'].get(status, 0)} |")
    lines += ['', '## Channels', '', '| Source | Mode | Fetch outcome | Status | Units | Personas fed | Reason |', '|---|---|---|---|---:|---|---|']
    for r in result['channels']:
        lines.append('| ' + ' | '.join(cell(v) for v in [r['name'], r.get('mode', ''), r.get('fetch_outcome', 'not_run'), r['status'], r['units'], ', '.join(r['personas_fed']), r.get('reason', '')]) + ' |')
    lines += ['', '## X donors', '', '| Donor | Status | Units | Roster persona cluster | Voice/exemplar used | Usage |', '|---|---|---:|---|---|---|']
    for r in result['donors']:
        lines.append('| ' + ' | '.join(cell(v) for v in [r['name'], r['status'], r['units'], r['persona_cluster'],
                                                       'yes' if r['voice_exemplar_used'] else 'no', r['usage']]) + ' |')
    lines.append('')
    lines += ['## Next to build', '', 'Score = 4 verified + 3 free/public + persona gap weight / (1 + personas fed) + 4 licence permits paraphrase.',
              'Gap weights: Chinese US-stock commentary 5; short-term trading/crypto 3; other 1. Licence eligibility is shown separately; a score is not licence approval.', '']
    for i, r in enumerate(result['next_to_build'], 1):
        lines.append(f"{i}. {r['name']} — {r['score']:g}; {json.dumps(r['score_factors'], ensure_ascii=False)}")
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--expansion', type=Path, default=Path('/workspace/x/source_expansion.json'))
    ap.add_argument('--channels', type=Path, default=ROOT/'live/channels.json')
    ap.add_argument('--runs', type=Path, nargs='+', default=[])
    ap.add_argument('--registry', type=Path, default=ROOT/'live/source_registry.json')
    ap.add_argument('--licence', type=Path, default=ROOT/'live/source_licence.json')
    ap.add_argument('--roster', type=Path, default=ROOT/'live/donors/roster.json')
    ap.add_argument('--store', type=Path, required=True)
    ap.add_argument('--donor-tags', type=Path, default=ROOT/'live/donors/tags')
    ap.add_argument('--out-md', type=Path, required=True)
    ap.add_argument('--out-json', type=Path, required=True)
    args = ap.parse_args()
    from live.adapters.channels import load_channels
    reports = []
    for directory in args.runs:
        paths = [directory] if directory.is_file() else sorted(directory.rglob('report.json'), key=lambda p: (p.stat().st_mtime_ns, str(p)))
        reports.extend(json.loads(p.read_text()) for p in paths)
    result = audit({'sources': []}, *(json.loads(p.read_text()) for p in (args.registry, args.licence, args.roster)),
                   args.store, args.donor_tags, planned=load_channels(args.channels), runs=reports)
    for path, text in [(args.out_md, markdown(result)), (args.out_json, json.dumps(result, ensure_ascii=False, indent=2)+'\n')]:
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
    print(json.dumps({'summary': result['summary'], 'donor_count': result['donor_count']}))

if __name__ == '__main__': main()
