#!/usr/bin/env python3
"""Read-only freshness coverage and persona inventory report."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live import freshness
from scripts.backfill_freshness import read_rows

STATES = ('fresh', 'stale', 'expired', 'evergreen', 'unknown')
BINS = ('0-1d', '2-3', '4-7', '8-14', '15-30', '31-90', '>90', 'unknown')


def sidecar(store, name):
    path = Path(store) / (name + '.jsonl')
    entries = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                entries[entry['unit_id']] = entry
    return entries


def build_report(store, now=None):
    rows = read_rows(store)
    dates = sidecar(store, 'freshness')
    tags = sidecar(store, 'persona_tags')
    sources, flags, histogram, states = Counter(), Counter(), Counter(dict.fromkeys(BINS, 0)), Counter(dict.fromkeys(STATES, 0))
    personas = {}
    # Include known personas even when none of their tags meets the threshold.
    from live.jev_front import PERSONAS
    for p in PERSONAS:
        personas[p] = dict.fromkeys(STATES, 0)
    covered = unknown = 0
    for row in rows:
        uid = row['unit_id']
        derived = dates.get(uid) or freshness.derive_dates(row)
        unit = dict(row['unit'], **{k: derived[k] for k in ('as_of', 'as_of_source', 'date_unknown', 'freshness_flags')})
        state = freshness.status(dict(row, unit=unit), now)
        states[state['status']] += 1
        covered += bool(derived['as_of'])
        unknown += bool(derived['date_unknown'])
        sources[derived['as_of_source']] += 1
        flags.update(derived['freshness_flags'])
        age = state['age_days']
        bucket = 'unknown' if age is None else next((b for bound, b in zip((1,3,7,14,30,90), BINS) if age <= bound), '>90')
        histogram[bucket] += 1
        for persona, tag in tags.get(uid, {}).get('tags', {}).items():
            confidence = tag.get('confidence')
            if tag.get('verdict') == 'relevant' and type(confidence) in (int,float) and confidence >= .7:
                personas.setdefault(persona, dict.fromkeys(STATES,0))[state['status']] += 1
    for counts in personas.values():
        counts['starving'] = counts['fresh'] < 5
    total = len(rows)
    return {'now': freshness._day(now).isoformat(), 'units': total,
            'coverage': {'with_as_of': covered, 'with_as_of_pct': round(100*covered/total,2) if total else 0,
                         'date_unknown': unknown, 'date_unknown_pct': round(100*unknown/total,2) if total else 0,
                         'as_of_source_counts': dict(sources), 'flag_counts': dict(flags)},
            'age_histogram': dict(histogram), 'statuses': dict(states), 'personas': personas}


def markdown(report):
    c = report['coverage']
    lines = [f"# Freshness inventory — {report['now']}", '',
             f"{report['units']} units; {c['with_as_of_pct']}% with as_of; {c['date_unknown_pct']}% date unknown.", '',
             '| Age | Units |', '| --- | ---: |']
    lines += [f'| {b} | {n} |' for b,n in report['age_histogram'].items()]
    lines += ['', '| Persona | Fresh | Stale | Expired | Evergreen | Unknown | Starving |', '| --- | ---: | ---: | ---: | ---: | ---: | --- |']
    lines += ['| '+p+' | '+' | '.join(str(c[k]) for k in (*STATES,'starving'))+' |' for p,c in report['personas'].items()]
    lines += ['', 'Date sources: '+json.dumps(report['coverage']['as_of_source_counts'],ensure_ascii=False),
              '', 'Flags: '+json.dumps(report['coverage']['flag_counts'],ensure_ascii=False)]
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True)
    parser.add_argument('--now')
    parser.add_argument('--out-json', type=Path, required=True)
    parser.add_argument('--out-md', type=Path)
    args = parser.parse_args()
    report = build_report(args.store, args.now)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    if args.out_md:
        args.out_md.write_text(markdown(report))
    print(json.dumps({k:report[k] for k in ('units','coverage','age_histogram','statuses','personas')},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
