#!/usr/bin/env bash
set -euo pipefail
export FD_PACK_AUGMENT=1
cd /workspace/fd_new/Finance_Distillation
DAY=$(TZ=Europe/London date +%F)
RUN=/workspace/x/ingest_runs
mkdir -p "$RUN"
exec >> "$RUN/$DAY.cron.log" 2>&1
export ACCOUNT_CONTENT_PROVIDER=erisedai_relay
export ACCOUNT_RELAY_BASE_URL=https://api.erisedai.com/v1
export ACCOUNT_RELAY_API_KEY="$RELAY_API_KEY"
/workspace/fd_venv/bin/python scripts/daily_ingest.py "$@"
