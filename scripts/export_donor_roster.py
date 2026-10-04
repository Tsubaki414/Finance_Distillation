"""Export the verified X donor roster (fd_donor_roster.json) to live/donors/roster.json.

Keeps what the pipeline needs: per donor lang / category / persona cluster /
verified / donor_fit / style summary, and the persona clusters with weighted
core donors (>= 5, each <= 0.35) and bench. Read-only on the input.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEEP = ('handle', 'lang', 'category', 'persona_cluster', 'verified', 'donor_fit', 'promo_heavy',
        'followers', 'latest_post', 'posts_per_day', 'frequency', 'median_chars')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('roster', type=Path)
    ap.add_argument('--out', type=Path, default=ROOT / 'live' / 'donors' / 'roster.json')
    args = ap.parse_args()
    src = json.loads(args.roster.read_text())
    donors = {}
    for row in src['rows']:
        if not row.get('exists'):
            continue
        d = {k: row.get(k) for k in KEEP}
        d['style_tags'] = (row.get('style') or {}).get('tags') or []
        d['tone'] = (row.get('style') or {}).get('tone') or []
        donors[row['handle'].lower()] = d
    out = {'version': '1', 'generated': src['generated'], 'method': src['method'],
           'activity_cutoff': src['activity_cutoff'], 'review_status': 'draft (D2 pending Fiona)',
           'use': 'voice exemplars only: style, never facts, numbers or phrases',
           'persona_clusters': {k: {'lang': v['lang'], 'donors': [{'handle': d['handle'], 'weight': d['weight']} for d in v['donors']],
                                    'bench': v['bench']} for k, v in src['persona_clusters'].items()},
           'donors': donors}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print(args.out, len(donors), 'donors', len(out['persona_clusters']), 'clusters')


if __name__ == '__main__':
    main()
