"""Traceability check for step 3: pick a sentence at random, open it at its origin.

The delivery criterion is not "a source pack exists" but "any sentence in any package can be
opened at the exact characters it came from". This samples segments, follows each cited fact to
its character range in the original release, and reads those characters back out of the file.

A sample is only counted as traced when the recorded quote equals what is actually at that
offset in the artifact. Nothing here trusts the package's own claim.

Run: .venv/bin/python -B content/traceback_check.py [--samples=40] [--seed=7]
"""
from pathlib import Path
import sys, json, random, hashlib, datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qa.gates import parse_numbers
from content.generate_slotted import CALENDAR


def main():
    """Open a random sentence at its origin, whichever pipeline and whichever source document.

    This used to load one packet and one artifact path, so it could only ever audit the frozen
    BLS event — the daily output was never checked at all.
    """
    args = {a.split('=', 1)[0][2:]: a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--')}
    samples = int(args.get('samples', 40))
    seed = int(args.get('seed', 7))

    packets, artifacts = {}, {}
    for d in (ROOT / 'evidence_loop/sources/packets', ROOT / 'live/store/packets'):
        for f in sorted(d.glob('*.json')) if d.is_dir() else []:
            pk = json.loads(f.read_text())
            packets[pk['id']] = pk
            ap = ROOT / pk['artifact_path']
            artifacts[pk['id']] = ap.read_text() if ap.is_file() else pk.get('full_narrative', '')

    rows = []
    for p in sorted((ROOT / 'content/packages').glob('*.json')):
        d = json.loads(p.read_text())
        if d.get('content_status') != 'ready_for_pipeline':
            continue
        pid = d.get('source_id')
        if pid not in packets:
            continue
        for seg in d.get('sentence_to_source_ledger') or []:
            rows.append((d, seg, pid))
    if not rows:
        print('no packages to audit')
        return

    rng = random.Random(seed)
    picked = rng.sample(rows, min(samples, len(rows)))

    traced, results = 0, []
    for d, seg, pid in picked:
        pk, raw = packets[pid], artifacts[pid]
        facts = {f['id']: f for f in pk['facts']}
        blocks = {b['id'] for b in pk['blocks']}
        checks = []
        for fid in seg.get('fact_ids') or []:
            fx = facts.get(fid)
            if not fx:
                checks.append({'fact_id': fid, 'ok': False, 'why': 'fact not in packet'})
                continue
            span = fx['source_span']
            at = raw[span['start']:span['end']]
            ok = at.strip() == span['quote'].strip() and all(
                b in blocks for b in fx['source_block_ids'])
            checks.append({'fact_id': fid, 'char_span': [span['start'], span['end']],
                           'expected_quote': span['quote'], 'read_back': at, 'ok': ok,
                           'url': pk['primary_url']})
        ok = bool(checks) and all(c['ok'] for c in checks)
        traced += ok
        results.append({'package_id': d['id'], 'origin': d.get('origin', 'curated'),
                        'who': d.get('persona_name'), 'form': d.get('form'),
                        'packet': pid, 'segment_id': seg['sentence_id'],
                        'text': seg['text'][:70], 'fact_count': len(checks),
                        'traced': ok, 'checks': checks})

    traceable = [r for r in results if r['fact_count']]
    by_origin = {}
    for r in results:
        b = by_origin.setdefault(r['origin'], {'sampled': 0, 'with_fact': 0, 'traced': 0})
        b['sampled'] += 1
        b['with_fact'] += bool(r['fact_count'])
        b['traced'] += bool(r['traced'])

    out = {'run_id': 'trace-' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S'),
           'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'packets_available': len(packets),
           'segments_available': len(rows), 'sampled': len(picked),
           'fact_bearing_sampled': len(traceable), 'traced': traced,
           'trace_rate_of_fact_bearing': round(traced / max(len(traceable), 1), 4),
           'by_origin': by_origin, 'seed': seed,
           'method': ('each cited fact is followed to its character offsets in its own source '
                      'document and read back; nothing is taken on the package\'s word'),
           'results': results}
    (ROOT / 'content/traceback.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(f"packets {len(packets)} · segments {len(rows)} · sampled {len(picked)}")
    print(f"fact-bearing {len(traceable)} · traced {traced} "
          f"({out['trace_rate_of_fact_bearing']:.0%})")
    for o, b in by_origin.items():
        print(f"  {o:9} sampled {b['sampled']:>3}  with a fact {b['with_fact']:>3}  "
              f"traced {b['traced']:>3}")
    for r in results:
        if r['fact_count'] and not r['traced']:
            print(f"  UNTRACED {r['origin']}/{r['form']}/{r['segment_id']}")
    return out


if __name__ == '__main__':
    main()
