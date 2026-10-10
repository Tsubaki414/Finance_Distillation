#!/usr/bin/env python
"""Build live/donors/donor_rates.json from the donor corpus.

Usage:
    /workspace/fd_venv/bin/python scripts/build_donor_rates.py [--out PATH]

Aggregates only — no donor text is written to the output file.
Safe to commit (check: assert no post text in JSON before doing so).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live import donor_rates


def main():
    ap = argparse.ArgumentParser(description='Build live/donors/donor_rates.json')
    ap.add_argument('--out', default=str(donor_rates.JSON),
                    help='output path (default: live/donors/donor_rates.json)')
    args = ap.parse_args()

    print('building donor rates …', file=sys.stderr)
    data = donor_rates.build_all()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n')

    accts = data['accounts']
    n = len(accts)
    fallbacks = sum(1 for v in accts.values() if v.get('fallback'))
    print(f'accounts={n}  with_fallback={fallbacks}  langs={list(data["fallback"].keys())}',
          file=sys.stderr)
    print(f'written: {out}', file=sys.stderr)

    # safety: assert no long text strings (donor post content) ended up in the file
    raw = out.read_text()
    words = max(len(s) for s in raw.split('"') if s.strip())
    assert words < 300, f'suspiciously long string ({words} chars) in donor_rates.json — check for post text'
    print('safety check passed: no long strings in output', file=sys.stderr)


if __name__ == '__main__':
    main()
