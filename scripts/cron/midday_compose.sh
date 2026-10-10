#!/usr/bin/env bash
# Oct 10: midday fresh-news compose. Two languages, independent invocations.
#   zh: 10:30 BJT = 03:30 London BST (until Oct 25) / 02:30 London GMT (after Oct 25)
#       cron: 30 2 * * * (BST: 30 3 * * *; switch after Oct 25)
#   en: 19:30 BJT = 12:30 London BST (until Oct 25) / 11:30 London GMT (after Oct 25)
#       cron: 30 11 * * * (BST: 30 12 * * *; switch after Oct 25)
# Usage: midday_compose.sh <zh|en>
# Step 1: light ingest for the language (X + flashes, short window, own runs-dir).
# Step 2: FD_MIDDAY=1 compose via daily_compose.sh so the dashboard rebuild/redeploy happens.
#   Accounts of the wrong language are skipped by FD_MIDDAY_LANG.
#   Only accounts with a stale or absent standalone for today qualify (>24h published_at, or none).
#   Candidate sources must be ≤ FD_MIDDAY_MAX_AGE_H (default 6) hours old at compose time.
#   One standalone per account; no 回看/常青, no engagement.
#   FD_MIDDAY_REPLACE=1 (default): new draft supersedes the account's stale unposted standalone.
# Both steps are skipped when FD_MIDDAY_COMPOSE=0.
set -euo pipefail
cd /workspace/fd_new/Finance_Distillation

LANG_ARG="${1:-}"
if [[ "$LANG_ARG" != "zh" && "$LANG_ARG" != "en" ]]; then
    echo "usage: midday_compose.sh <zh|en>"; exit 1
fi

[[ "${FD_MIDDAY_COMPOSE:-1}" == "0" ]] && { echo "FD_MIDDAY_COMPOSE=0: midday compose off"; exit 0; }

# Logging: /workspace/x/midday_runs/<London date>.log
LOG_DIR=/workspace/x/midday_runs
mkdir -p "$LOG_DIR"
exec >> "$LOG_DIR/$(TZ=Europe/London date +%F).log" 2>&1
printf 'START %s lang=%s\n' "$(date -Is)" "$LANG_ARG"
trap 'status=$?; printf "END %s lang=%s exit_code=%s\n" "$(date -Is)" "$LANG_ARG" "$status"' EXIT

# Beijing hour gate: zh 09-12, en 18-21
H=$(TZ=Asia/Shanghai date +%-H)
if [[ "$LANG_ARG" == "zh" ]]; then
    if (( H < 9 || H > 12 )); then echo "Beijing hour $H outside zh window 09-12: skip"; exit 0; fi
else
    if (( H < 18 || H > 21 )); then echo "Beijing hour $H outside en window 18-21: skip"; exit 0; fi
fi

# Own lock; also skip when daily_compose.sh or daily_ingest.py is running
exec 9>/tmp/fd_midday_compose_"${LANG_ARG}".lock
if ! flock -n 9; then echo "previous midday_compose (${LANG_ARG}) still running: skip"; exit 0; fi
if flock -n /workspace/x/compose_runs/.daily_compose.lock 2>/dev/null; then
    # We could acquire the nightly lock; release it immediately (we just checked, we don't want to hold it)
    exec 8>/workspace/x/compose_runs/.daily_compose.lock
    if ! flock -n 8; then
        echo "daily_compose.sh lock is held: skip"
        exit 0
    fi
fi
if pgrep -f "python[0-9.]* scripts/daily_(compose|ingest)\.py" >/dev/null 2>&1; then
    echo "daily_compose or daily_ingest is running: skip"; exit 0
fi

# Key checks (never print values)
SUBROUTER_ENV="${FD_SUBROUTER_ENV:-$HOME/.secrets/subrouter.env}"
if [[ -z "${SUBROUTER_API_KEY:-}" && -r "$SUBROUTER_ENV" ]]; then set -a; . "$SUBROUTER_ENV"; set +a; fi
for k in SUBROUTER_API_KEY; do
    if [[ -n "${!k:-}" ]]; then echo "key $k: set"; else echo "key $k: missing"; exit 2; fi
done
# Midday compose uses subrouter only ($0 per draft); never the paid micuapi fallback
unset GEMINI_RELAY_API_KEY

# ── Step 1: light ingest ────────────────────────────────────────────────────
INGEST_RUNS=/workspace/x/ingest_runs/midday
mkdir -p "$INGEST_RUNS"
echo "=== ingest step (X + flashes, lang=$LANG_ARG) ==="
/workspace/fd_venv/bin/python scripts/daily_ingest.py \
    --only x flashes \
    --x-lang "$LANG_ARG" \
    --x-window-hours 8 \
    --flash-window-hours 8 \
    --no-news-leads \
    --no-dashboard \
    --runs-dir "$INGEST_RUNS" \
    --cost-cap-usd "${FD_MIDDAY_INGEST_USD:-0.4}" \
    || echo "midday ingest failed: $? (continuing to compose with existing store)"

# ── Step 2: compose via daily_compose.sh (handles dashboard rebuild + redeploy) ─
echo "=== compose step (FD_MIDDAY=1, lang=$LANG_ARG) ==="
FD_DAILY_COMPOSE=1 \
FD_MIDDAY=1 \
FD_MIDDAY_LANG="$LANG_ARG" \
FD_MIDDAY_MAX_AGE_H="${FD_MIDDAY_MAX_AGE_H:-6}" \
FD_MIDDAY_REPLACE="${FD_MIDDAY_REPLACE:-1}" \
FD_DAILY_COMPOSE_BUDGET_USD="${FD_MIDDAY_USD:-1}" \
FD_FILL_ROUNDS=0 \
FD_ARCHIVE=0 \
FD_ENGAGE_ONLY=0 \
    bash scripts/cron/daily_compose.sh \
        --day "$(TZ=Asia/Shanghai date +%F)" \
        --per-account 1 \
        --midday \
        || echo "midday compose step failed: $?"
