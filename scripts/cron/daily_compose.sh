#!/usr/bin/env bash
# Daily auto-compose for the 20 main accounts -> review inbox (no publishing). Off unless FD_DAILY_COMPOSE=1.
# Schedule after daily_ingest.sh (or let daily_ingest.sh chain it). Model: Gemini via FD_GEMINI_PROVIDER (relay default, or official),
# FD_GEMINI_MODEL switches every Gemini stage (default gemini-3-flash-preview). No Opus fallback.
set -euo pipefail
cd /workspace/fd_new/Finance_Distillation
if [[ "${FD_DAILY_COMPOSE:-0}" != "1" ]]; then echo "FD_DAILY_COMPOSE is not 1: compose off"; exit 0; fi
# Log name only: London date of the run. The drafting day (inbox / CSV / media / dashboard) is the Beijing date,
# computed in daily_compose.py: the 23:13 London run on 10-07 logs to 2026-10-07.cron.log and drafts 2026-10-08.
DAY=$(TZ=Europe/London date +%F)
LOG=/workspace/x/compose_runs/$DAY.cron.log
mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1
printf 'START %s\n' "$(date -Is)"
trap 'status=$?; printf "END %s exit_code=%s\n" "$(date -Is)" "$status"' EXIT
# FD_GEMINI_PROVIDER=relay (default since Oct 7: micuapi, GEMINI_RELAY_API_KEY) | official (GEMINI_API_KEY).
GKEY=GEMINI_RELAY_API_KEY; [[ "${FD_GEMINI_PROVIDER:-relay}" == "official" ]] && GKEY=GEMINI_API_KEY
if [[ -n "${!GKEY:-}" ]]; then echo "key $GKEY: set"; else echo "key $GKEY: missing"; exit 2; fi
export FD_PACK_AUGMENT=1
/workspace/fd_venv/bin/python scripts/persona_factory.py >/dev/null   # refresh universes (no model calls)
# FD_HOTSPOT (default 1): /admin decisions of the last days -> per-account approve rates by angle / 母题 type + edit
# diffs (live/store/feedback, local), read next day as a soft prior. No model calls; never fatal.
if [[ "${FD_HOTSPOT:-1}" != "0" ]]; then
    /workspace/fd_venv/bin/python scripts/feedback_priors.py --pull || echo "feedback priors failed (compose unaffected)"
fi
BUDGET="${FD_DAILY_COMPOSE_BUDGET_USD:-8}"
# The ml/budget ledger is a cumulative lifetime safety cap; give tonight's run headroom = its own budget + $1 reserve,
# so the per-run --budget-usd is the real daily limit (10-08: ledger at $99.86/$100 silently blocked every draft).
/workspace/fd_venv/bin/python -c "import sys; from ml import budget; d=budget._load(); s=float(d.get('spent_usd') or 0); c=float(d.get('cap_usd') or 0); n=s+float(sys.argv[1])+1.0; budget.set_cap(n) if n>c else None; print(f'ledger cap {c:.2f} -> {max(n,c):.2f} (spent {s:.2f})')" "$BUDGET"
/workspace/fd_venv/bin/python scripts/daily_compose.py --per-account "${FD_DAILY_COMPOSE_PER_ACCOUNT:-2}" \
    --budget-usd "$BUDGET" "$@"
# Rebuild the operator copy-paste dashboard (static HTML + per-day CSV); system python3 has PIL for avatar thumbnails.
/workspace/fd_venv/bin/python scripts/build_ops_dashboard.py || echo "ops dashboard rebuild failed (compose result unaffected)"
# Redeploy the static ops page to Vercel (project fd-ops-dashboard, linked in the ops dir). Non-fatal; skip with
# FD_OPS_DEPLOY=0. The ops dir only holds index.html + per-day CSVs (no keys, no donor text).
if [[ "${FD_OPS_DEPLOY:-1}" == "1" ]]; then
    OPS=${FD_OPS_DIR:-/workspace/x/dashboard/ops}
    VERCEL=$(command -v vercel || echo /home/box/.local/bin/vercel)
    if [[ -x "$VERCEL" && -d "$OPS/.vercel" ]]; then
        (cd "$OPS" && timeout 300 "$VERCEL" deploy --prod --yes) || echo "ops dashboard redeploy failed (compose result unaffected)"
    else
        echo "ops dashboard redeploy skipped: vercel CLI or $OPS/.vercel missing"
    fi
fi
