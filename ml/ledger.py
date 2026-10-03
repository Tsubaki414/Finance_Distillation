"""Experiment ledger. Fixes the Trackio gap where the authoritative run was never recorded.

The published metrics came from run ml-20260906T025040 while Trackio only held two earlier runs
with a different clean_count, and the artifacts table was empty. Anything we publish from now on
has to be queryable with its config, split, seed and artifact hashes.

Trackio stays local. No HF Hub push, no Space sync.
"""
from pathlib import Path
import json, hashlib, datetime, sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'ml_experiments/trackio/financial-persona.db'
MIRROR = ROOT / 'ml_experiments/ledger.json'


def sha(path):
    p = ROOT / path if not str(path).startswith('/') else Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def trackio_runs():
    """Read-only view of what Trackio actually holds."""
    if not DB.exists():
        return []
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    try:
        rows = con.execute('SELECT DISTINCT run_name FROM metrics').fetchall()
        return sorted(r[0] for r in rows if r[0])
    finally:
        con.close()


def record(run_id, kind, config, metrics, artifacts, splits=None, notes=None):
    """Append one entry to the local mirror with artifact hashes attached."""
    MIRROR.parent.mkdir(parents=True, exist_ok=True)
    ledger = json.loads(MIRROR.read_text()) if MIRROR.exists() else {'runs': []}
    entry = {
        'run_id': run_id, 'kind': kind,
        'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'config': config, 'metrics': metrics, 'splits': splits or {},
        'artifacts': [{'path': str(a), 'sha256': sha(a)} for a in artifacts],
        'in_trackio': run_id in trackio_runs(),
        'notes': notes,
    }
    ledger['runs'] = [r for r in ledger['runs'] if r['run_id'] != run_id] + [entry]
    ledger['updated_at'] = entry['recorded_at']
    ledger['trackio_runs'] = trackio_runs()
    ledger['sync_gap'] = [r['run_id'] for r in ledger['runs'] if not r['in_trackio']]
    MIRROR.write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
    return entry


def backfill_authoritative():
    """Register the run whose numbers are published but which Trackio never captured."""
    summary = json.loads((ROOT / 'ml_experiments/run_summary.json').read_text())
    rid = summary['run_id']
    return record(
        run_id=rid, kind='corpus_baselines',
        config={'seed': 42, 'dataset_sha256': summary['dataset_sha256'],
                'raw': summary['raw'], 'clean': summary['clean'],
                'labels': 'rules-v2 weak labels, not human gold'},
        metrics={'classification': summary['classification'],
                 'authorship': summary['authorship']},
        splits={'classification': 'strict-policy reviewed rows, silver labels',
                'authorship': 'within-author chronological 80/20, thread and exact-duplicate purge'},
        artifacts=['ml_experiments/A_finance_classification.json',
                   'ml_experiments/B_authorship.json',
                   'ml_experiments/run_summary.json',
                   'topic_clusters/clusters.json',
                   'data/clean_posts.jsonl'],
        notes=('Backfilled. Trackio held only ml-20260906T014631 and ml-20260906T021854 with '
               'clean_count 1876 and 1840; this run has clean 1825 and is the one whose metrics '
               'are published. Classification remains circular against its own silver labels and '
               'must not be quoted as accuracy.'))


if __name__ == '__main__':
    e = backfill_authoritative()
    led = json.loads(MIRROR.read_text())
    print(json.dumps({'registered': e['run_id'], 'in_trackio': e['in_trackio'],
                      'artifacts': len(e['artifacts']),
                      'trackio_runs': led['trackio_runs'],
                      'sync_gap': led['sync_gap']}, ensure_ascii=False, indent=1))
