#!/usr/bin/env bash
# Oct 9 (Fiona: ride big-account traffic): daytime engagement pull. Schedule at 03:00 and 09:00 London (11:00 / 16:00
# Beijing), on top of the nightly daily_ingest.sh. Two steps, no publishing:
#   1. fetch the ENGAGE watchlist only (live/engagement.subscriptions: high-traffic same-lane accounts; batched
#      RapidAPI search with min_faves, shares engagement.json engage_daily_call_cap with the nightly) and extract the
#      qualifying posts into the content store (X ring fence FD_ENGAGE_PULL_X_USD, cap FD_ENGAGE_PULL_CAP_USD);
#   2. an FD_ENGAGE_ONLY fill for today's Beijing day: only reply / quote drafts on fresh targets (reply <= 6h,
#      quote <= 12h at the slot; one of our accounts per target post; cold accounts 1 quote + 1 reply a day), budget
#      FD_ENGAGE_FILL_USD, subrouter only (the paid micuapi fallback key is unset), no 回看, then the ops dashboard
#      rebuild + redeploy that daily_compose.sh does.
# Skips when another compose run is active or the Beijing hour is outside 08-21. FD_ENGAGE_PULL=0 turns it off.
set -euo pipefail
cd /workspace/fd_new/Finance_Distillation
[[ "${FD_ENGAGE_PULL:-1}" == "0" ]] && { echo "FD_ENGAGE_PULL=0: off"; exit 0; }
RUN=/workspace/x/engage_runs
mkdir -p "$RUN"
exec >> "$RUN/$(TZ=Europe/London date +%F).log" 2>&1
printf 'START %s\n' "$(date -Is)"
trap 'status=$?; printf "END %s exit_code=%s\n" "$(date -Is)" "$status"' EXIT
H=$(TZ=Asia/Shanghai date +%-H)
if (( H < 8 || H > 21 )); then echo "Beijing hour $H outside 08-21: skip"; exit 0; fi
if pgrep -f "python[0-9.]* scripts/daily_(compose|ingest)\.py" >/dev/null; then   # not a CC prompt mentioning them
    echo "another compose / ingest run is active: skip"; exit 0
fi
SUBROUTER_ENV="${FD_SUBROUTER_ENV:-$HOME/.secrets/subrouter.env}"
if [[ -z "${SUBROUTER_API_KEY:-}" && -r "$SUBROUTER_ENV" ]]; then set -a; . "$SUBROUTER_ENV"; set +a; fi
for k in SUBROUTER_API_KEY RAPID_X_API_KEY; do
    if [[ -n "${!k:-}" ]]; then echo "key $k: set"; else echo "key $k: missing"; exit 2; fi
done
# X post extraction (content units) uses the erisedai relay like the nightly ingest (same env as daily_ingest.sh);
# it is the only paid step here and is capped by FD_ENGAGE_PULL_CAP_USD per pull.
export ACCOUNT_CONTENT_PROVIDER=erisedai_relay
if [[ -n "${ACCOUNT_RELAY_API_KEY:-}" || -n "${RELAY_API_KEY:-}" ]]; then
    export ACCOUNT_RELAY_BASE_URL="${ACCOUNT_RELAY_BASE_URL:-https://api.erisedai.com/v1}"
    export ACCOUNT_RELAY_API_KEY="${ACCOUNT_RELAY_API_KEY:-${RELAY_API_KEY:-}}"
else
    echo "key RELAY_API_KEY: missing (X extraction skipped; the fill uses targets already in the store)"
    unset ACCOUNT_RELAY_BASE_URL ACCOUNT_RELAY_API_KEY
fi
unset GEMINI_RELAY_API_KEY   # compose: subrouter only, no paid micuapi fallback on the daytime pulls
export FD_PACK_AUGMENT=1
ER=/workspace/x/ingest_runs/engage
/workspace/fd_venv/bin/python scripts/daily_ingest.py --only x --x-engage-only --no-flashes --no-news-leads \
    --no-dashboard --runs-dir "$ER" \
    --cost-cap-usd "${FD_ENGAGE_PULL_CAP_USD:-0.5}" --x-budget-usd "${FD_ENGAGE_PULL_X_USD:-0.4}" > "$ER/last.out" 2>&1 \
    || echo "engage pull ingest failed: $?"
/workspace/fd_venv/bin/python - "$ER/$(TZ=Asia/Shanghai date +%Y%m%d).json" <<'PY' || true
import json, sys
d = json.load(open(sys.argv[1]))
x = d.get('x') or {}
print('engage pull', d.get('status'), json.dumps({k: x.get(k) for k in ('posts_fetched', 'selected', 'filtered', 'engage')}, ensure_ascii=False))
print('cost', json.dumps(d.get('cost_usd')), 'failed steps', [s['id'] + ': ' + str(s.get('error'))[:160] for s in d.get('steps', []) if s.get('status') != 'ok'])
PY
FD_DAILY_COMPOSE=1 FD_ENGAGE_ONLY=1 FD_ARCHIVE=0 FD_FILL_ROUNDS="${FD_ENGAGE_FILL_ROUNDS:-1}" \
    FD_DAILY_COMPOSE_PER_ACCOUNT="${FD_ENGAGE_PER_ACCOUNT:-4}" FD_DAILY_COMPOSE_BUDGET_USD="${FD_ENGAGE_FILL_USD:-1}" \
    bash scripts/cron/daily_compose.sh --day "$(TZ=Asia/Shanghai date +%F)" || echo "engage fill failed: $?"
