#!/usr/bin/env bash
# Canonical test runner (the one behind the 22-failure baseline). Uses the project venv, which has pytest;
# the system /usr/bin/python3 has no pytest, and `python -m unittest` does not collect the pytest-style tests.
set -euo pipefail
cd "$(dirname "$0")/.."
exec /workspace/fd_venv/bin/python -m pytest -q -p no:cacheprovider --tb=line -rf tests/ \
  --ignore=tests/test_crosslang.py --ignore=tests/test_evergreen_delivery.py --ignore=tests/test_evergreen_output_gate.py \
  --ignore=tests/test_legacy_isolation.py --ignore=tests/test_live_audit.py "$@"
