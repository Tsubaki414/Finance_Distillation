#!/usr/bin/env python3
"""Print current account/source/provider configuration and persisted runtime state.

Read-only: no source fetch, paid model call, draft or service change.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.pipeline_health import inventory


if __name__ == '__main__':
    result = inventory()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['configuration_ready'] else 1)
