#!/usr/bin/env python3
"""Build v2 descriptive donor voice cards from a local corpus with optional qualitative analysis."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.voice_cards import build_cards, write_cards


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--posts-dir', type=Path, required=True)
    p.add_argument('--tags-dir', type=Path, required=True)
    p.add_argument('--roster', type=Path, default=Path('live/donors/roster.json'))
    p.add_argument('--out', type=Path, default=Path('live/personas/voice_cards'))
    p.add_argument('--llm-cmd', default='claude -p')
    p.add_argument('--clusters', nargs='+', help='Cluster names, separated by spaces or commas')
    p.add_argument('--sample-n', type=int, default=40)
    p.add_argument('--no-llm', action='store_true')
    p.add_argument('--raw-dir', type=Path, default=Path('live/personas/voice_cards/raw'))
    a = p.parse_args(argv)
    roster = json.loads(a.roster.read_text())
    clusters = {name for item in a.clusters for name in item.split(',')} if a.clusters else None
    if clusters is not None and clusters - roster['persona_clusters'].keys():
        p.error('Unknown clusters: ' + ', '.join(sorted(clusters - roster['persona_clusters'].keys())))
    if a.sample_n < 0:
        p.error('--sample-n must be nonnegative')
    attempts = {}

    def llm(name, prompt):
        attempts[name] = attempts.get(name, 0) + 1
        a.raw_dir.mkdir(parents=True, exist_ok=True)
        path = a.raw_dir / f'{name}.attempt-{attempts[name]}.txt'
        try:
            result = subprocess.run(shlex.split(a.llm_cmd), input=prompt, text=True,
                                    capture_output=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as exc:
            path.write_text(str(exc))
            raise RuntimeError(str(exc)) from exc
        path.write_text(result.stdout)
        if result.returncode:
            raise RuntimeError(f'LLM exited {result.returncode}: {result.stderr}')
        return result.stdout

    write_cards(build_cards(a.posts_dir, a.tags_dir, roster, llm=None if a.no_llm else llm,
                            clusters=clusters, sample_n=a.sample_n), a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
