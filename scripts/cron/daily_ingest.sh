#!/usr/bin/env bash
set -euo pipefail
export FD_PACK_AUGMENT=1
cd /workspace/fd_new/Finance_Distillation
# `--preflight`: local checks only (relay config, EXTRACT route + key presence), printed to stdout; no ingest, no spend.
PREFLIGHT_ONLY=0
if [[ "${1:-}" == "--preflight" ]]; then PREFLIGHT_ONLY=1; shift; fi
DAY=$(TZ=Europe/London date +%F)
RUN=/workspace/x/ingest_runs
mkdir -p "$RUN"
if [[ $PREFLIGHT_ONLY == 0 ]]; then
    exec >> "$RUN/$DAY.cron.log" 2>&1
    printf 'START %s\n' "$(date -Is)"
    trap 'status=$?; printf "END %s exit_code=%s\n" "$(date -Is)" "$status"' EXIT
fi
# Keys: the scheduled routine gets RELAY_API_KEY (erisedai, legacy stages) and GEMINI_API_KEY (official Gemini API: EXTRACT, COMPOSE, STANCE; Oct 7) from the
# same injected environment as interactive runs. Optional fallback for a bare environment: a user-owned key file
# (KEY=value lines; never committed), loaded only for keys that are not already set.
KEYS_FILE="${FD_KEYS_FILE:-$HOME/.config/fd/keys.env}"
if [[ -r "$KEYS_FILE" ]]; then
    while IFS='=' read -r k v; do
        [[ "$k" =~ ^(RELAY_API_KEY|GEMINI_API_KEY|GEMINI_RELAY_API_KEY|ACCOUNT_RELAY_API_KEY|ACCOUNT_RELAY_BASE_URL)$ ]] || continue
        [[ -n "${!k:-}" ]] && continue
        v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
        export "$k=$v"
    done < "$KEYS_FILE"
fi
for k in RELAY_API_KEY GEMINI_API_KEY; do
    if [[ -n "${!k:-}" ]]; then printf 'key %s: set\n' "$k"; else printf 'key %s: missing\n' "$k"; fi
done
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
if [[ $PREFLIGHT_ONLY == 1 ]]; then
    exec /workspace/fd_venv/bin/python scripts/daily_ingest_preflight.py "${preflight_args[@]}"
fi
/workspace/fd_venv/bin/python scripts/daily_ingest_preflight.py "${preflight_args[@]}" --failure-json "$RUN/$DAY.preflight_failed.json"
/workspace/fd_venv/bin/python scripts/daily_ingest.py --no-dashboard "$@"
# Oct 7 (fd20): chain the daily compose for the 20 main accounts. On by default; FD_DAILY_COMPOSE=0 turns it off.
export FD_DAILY_COMPOSE="${FD_DAILY_COMPOSE:-1}"
if [[ "${FD_DAILY_COMPOSE}" == "1" ]]; then bash scripts/cron/daily_compose.sh || echo "daily_compose failed: $?"; fi
