#!/usr/bin/env bash
set -euo pipefail
# Crontab (host timezone Europe/London):
# 30 7 * * 1-6 /workspace/fd_new/Finance_Distillation/scripts/cron/reportgem_daily.sh
# Needs REPORTGEM_MCP_URL, REPORTGEM_MCP_TOKEN, TYPESAFE_API_KEY, RELAY_API_KEY.
cd /workspace/fd_new/Finance_Distillation
DAY=$(TZ=Europe/London date +%F)
RUN=/workspace/x/reportgem/$DAY
mkdir -p "$RUN"
exec >> "$RUN/cron.log" 2>&1
export ACCOUNT_CONTENT_PROVIDER=erisedai_relay
export ACCOUNT_RELAY_BASE_URL=https://api.erisedai.com/v1
export ACCOUNT_RELAY_API_KEY="$RELAY_API_KEY"
/workspace/fd_venv/bin/python scripts/reportgem_daily.py --day "$DAY" --run "$RUN" --transport http --cap "${REPORTGEM_DAILY_CAP:-40}" --extract
