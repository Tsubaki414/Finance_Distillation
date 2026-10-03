#!/bin/sh
# Only writes handover/verification.json. No download, paid API, data mutation or .env reads.
set -eu
HANDOVER_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
if [ ! -x "$HANDOVER_ROOT/.venv/bin/python" ]; then
  echo 'FAIL project Python missing; verifier cannot run' >&2
  exit 3
fi
export PYTHONDONTWRITEBYTECODE=1
exec "$HANDOVER_ROOT/.venv/bin/python" -B "$HANDOVER_ROOT/scripts/verify_handover.py" "$@"
