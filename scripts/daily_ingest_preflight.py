#!/usr/bin/env python3
"""Check local daily ingestion prerequisites without network calls or spending."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.erisedai_distillation_client import relay_config


def check(store, runs_dir):
    result = {'status': 'ok', 'FD_PACK_AUGMENT': os.environ.get('FD_PACK_AUGMENT', '0'),
              'augment_note': 'Set FD_PACK_AUGMENT=1 to augment fact-only packs with existing non-fact units.'}
    for name, directory in [('store', Path(store)), ('runs-dir', Path(runs_dir))]:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=directory) as probe:
                probe.write(b'preflight')
                probe.flush()
        except OSError:
            return {**result, 'status': 'failed', 'reason': f'{name} is not writable'}
    try:
        with (Path(runs_dir) / 'daily_ingest.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # flock is released by close, even after a crash: an old file alone is not stale ownership.
            fcntl.flock(lock, fcntl.LOCK_UN)
    except OSError:
        return {**result, 'status': 'failed', 'reason': 'daily_ingest lock is held or inaccessible'}
    try:
        config = relay_config()
    except Exception:
        # Do not echo exception text: injected configuration could contain secrets.
        return {**result, 'status': 'failed', 'reason': 'relay configuration does not resolve'}
    result.update(configuration_source=config['configuration_source'], host=urlsplit(config['base_url']).hostname)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, default=Path('live/store/content_units'))
    parser.add_argument('--runs-dir', type=Path, default=Path('/workspace/x/ingest_runs'))
    parser.add_argument('--failure-json', type=Path)
    args = parser.parse_args()
    result = check(args.store, args.runs_dir)
    if result['status'] != 'ok' and args.failure_json:
        args.failure_json.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
