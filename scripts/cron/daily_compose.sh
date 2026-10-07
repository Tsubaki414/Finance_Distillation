#!/usr/bin/env bash
# Daily auto-compose for the 20 main accounts -> review inbox (no publishing). Off unless FD_DAILY_COMPOSE=1.
# Schedule after daily_ingest.sh (or let daily_ingest.sh chain it). Model: official Gemini API (GEMINI_API_KEY),
# FD_GEMINI_MODEL switches every Gemini stage (default gemini-3-flash-preview). No Opus fallback.
set -euo pipefail
cd /workspace/fd_new/Finance_Distillation
if [[ "${FD_DAILY_COMPOSE:-0}" != "1" ]]; then echo "FD_DAILY_COMPOSE is not 1: compose off"; exit 0; fi
DAY=$(TZ=Europe/London date +%F)
LOG=/workspace/x/compose_runs/$DAY.cron.log
mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1
printf 'START %s\n' "$(date -Is)"
trap 'status=$?; printf "END %s exit_code=%s\n" "$(date -Is)" "$status"' EXIT
if [[ -n "${GEMINI_API_KEY:-}" ]]; then echo "key GEMINI_API_KEY: set"; else echo "key GEMINI_API_KEY: missing"; exit 2; fi
export FD_PACK_AUGMENT=1
/workspace/fd_venv/bin/python scripts/persona_factory.py >/dev/null   # refresh universes (no model calls)
/workspace/fd_venv/bin/python scripts/daily_compose.py --per-account "${FD_DAILY_COMPOSE_PER_ACCOUNT:-2}" \
    --budget-usd "${FD_DAILY_COMPOSE_BUDGET_USD:-4}" "$@"
# Rebuild the operator copy-paste dashboard (static HTML + per-day CSV); system python3 has PIL for avatar thumbnails.
python3 scripts/build_ops_dashboard.py || echo "ops dashboard rebuild failed (compose result unaffected)"
