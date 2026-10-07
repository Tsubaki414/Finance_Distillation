#!/usr/bin/env bash
# Hourly chart refresh for today's / tomorrow's ready drafts (scripts/refresh_charts.py): refetch + re-render charts,
# rebuild / and /admin, `vercel deploy --prod --yes` only when an image changed. No model calls, no spend.
# Crontab (host timezone Europe/London; the Beijing-hour window is enforced below, so DST does not matter):
#   17 * * * * /workspace/fd_new/Finance_Distillation/scripts/cron/refresh_charts.sh
# Runs at minute 17 of 08:00-23:00 Beijing time; FD_CHART_REFRESH_ANY_HOUR=1 skips the window (manual runs).
set -euo pipefail
cd /workspace/fd_new/Finance_Distillation
H=$(TZ=Asia/Shanghai date +%-H)
if [[ "${FD_CHART_REFRESH_ANY_HOUR:-0}" != "1" && ( $H -lt 8 || $H -gt 23 ) ]]; then exit 0; fi
RUN=/workspace/x/chart_refresh
mkdir -p "$RUN"
exec >> "$RUN/$(TZ=Europe/London date +%F).log" 2>&1
# One run at a time: a run still deploying when the next hour fires makes the new one exit.
exec 9> "$RUN/refresh_charts.lock"
if ! flock -n 9; then printf 'SKIP %s previous run still holds the lock\n' "$(date -Is)"; exit 0; fi
printf 'START %s\n' "$(date -Is)"
trap 'status=$?; printf "END %s exit_code=%s\n" "$(date -Is)" "$status"' EXIT
export PATH="$HOME/.local/bin:$HOME/.local/opt/node22/bin:$PATH"   # vercel CLI + node for cron's bare PATH
/workspace/fd_venv/bin/python scripts/refresh_charts.py "$@"
