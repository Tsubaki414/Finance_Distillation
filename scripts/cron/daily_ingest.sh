#!/usr/bin/env bash
set -euo pipefail
export FD_PACK_AUGMENT=1
cd /workspace/fd_new/Finance_Distillation
DAY=$(TZ=Europe/London date +%F)
RUN=/workspace/x/ingest_runs
mkdir -p "$RUN"
exec >> "$RUN/$DAY.cron.log" 2>&1
printf 'START %s\n' "$(date -Is)"
trap 'status=$?; printf "END %s exit_code=%s\n" "$(date -Is)" "$status"' EXIT
export ACCOUNT_CONTENT_PROVIDER=erisedai_relay
if [[ -n "${ACCOUNT_RELAY_API_KEY:-}" || -n "${RELAY_API_KEY:-}" ]]; then
    export ACCOUNT_RELAY_BASE_URL="${ACCOUNT_RELAY_BASE_URL:-https://api.erisedai.com/v1}"
    export ACCOUNT_RELAY_API_KEY="${ACCOUNT_RELAY_API_KEY:-${RELAY_API_KEY:-}}"
else
    unset ACCOUNT_RELAY_BASE_URL ACCOUNT_RELAY_API_KEY
fi
# Forward local path overrides to preflight; remaining arguments belong to ingest.
preflight_args=()
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
    case "${args[i]}" in
        --store|--runs-dir) preflight_args+=("${args[i]}" "${args[i+1]}"); i=$((i+1)) ;;
        --store=*|--runs-dir=*) preflight_args+=("${args[i]}") ;;
    esac
done
/workspace/fd_venv/bin/python scripts/daily_ingest_preflight.py "${preflight_args[@]}" --failure-json "$RUN/$DAY.preflight_failed.json"
/workspace/fd_venv/bin/python scripts/daily_ingest.py --no-dashboard "$@"
