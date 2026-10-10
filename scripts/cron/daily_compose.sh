#!/usr/bin/env bash
# Daily auto-compose for the 20 main accounts -> review inbox (no publishing). Off unless FD_DAILY_COMPOSE=1.
# Schedule after daily_ingest.sh (or let daily_ingest.sh chain it). Model: Gemini via FD_GEMINI_PROVIDER (subrouter + micuapi fallback, relay, or official),
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
# Oct 9: one compose at a time (nightly, reruns, engage pulls); a second one exits instead of duplicating drafts.
exec 9>/workspace/x/compose_runs/.daily_compose.lock
if ! flock -n 9; then echo "another daily_compose.sh holds the lock: skip"; exit 0; fi
# Oct 8: subrouter (flat-rate Gemini relay) is the PRIMARY Gemini provider whenever SUBROUTER_API_KEY is set; micuapi
# (GEMINI_RELAY_API_KEY) is the automatic same-model fallback. The key file is private (chmod 600, outside the repo,
# never committed, printed or logged; only key NAMES are logged). FD_GEMINI_PROVIDER=relay forces micuapi only.
SUBROUTER_ENV="${FD_SUBROUTER_ENV:-$HOME/.secrets/subrouter.env}"
if [[ -z "${SUBROUTER_API_KEY:-}" && -r "$SUBROUTER_ENV" ]]; then set -a; . "$SUBROUTER_ENV"; set +a; fi
# FD_GEMINI_PROVIDER=subrouter (default when SUBROUTER_API_KEY is set; micuapi fallback) | relay (micuapi,
# GEMINI_RELAY_API_KEY; default without the subrouter key) | official (GEMINI_API_KEY).
if [[ -n "${SUBROUTER_API_KEY:-}" ]]; then DEFPROV=subrouter; else DEFPROV=relay; fi
PROV="${FD_GEMINI_PROVIDER:-$DEFPROV}"
echo "gemini provider: $PROV"
if [[ "$PROV" == "subrouter" ]]; then
    if [[ -n "${SUBROUTER_API_KEY:-}" ]]; then echo "key SUBROUTER_API_KEY: set"; else echo "key SUBROUTER_API_KEY: missing (every call on the micuapi fallback)"; fi
    if [[ -n "${GEMINI_RELAY_API_KEY:-}" ]]; then echo "key GEMINI_RELAY_API_KEY (fallback): set"; else echo "key GEMINI_RELAY_API_KEY (fallback): missing (no fallback)"; fi
    if [[ -z "${SUBROUTER_API_KEY:-}" && -z "${GEMINI_RELAY_API_KEY:-}" ]]; then exit 2; fi
else
    GKEY=GEMINI_RELAY_API_KEY; [[ "$PROV" == "official" ]] && GKEY=GEMINI_API_KEY
    if [[ -n "${!GKEY:-}" ]]; then echo "key $GKEY: set"; else echo "key $GKEY: missing"; exit 2; fi
fi
export FD_PACK_AUGMENT=1
/workspace/fd_venv/bin/python scripts/persona_factory.py >/dev/null   # refresh universes (no model calls)
# Feedback loop (FD_FEEDBACK, default 1): /admin decisions of the last days (已发 flag included) -> per-account soft
# priors by angle / 母题 type / post_kind / format / media + stats.json for the /admin 反馈闭环 panel + edit diffs
# (live/store/feedback, local). Priors act only while FD_HOTSPOT is on. FD_FEEDBACK_V2=0: the v1 approve-rate rule.
# No model calls; never fatal.
if [[ "${FD_FEEDBACK:-1}" != "0" ]]; then
    /workspace/fd_venv/bin/python scripts/feedback_priors.py --pull || echo "feedback priors failed (compose unaffected)"
fi
# Oct 10 (FD_PERF_DAILY, default on): fetch yesterday's perf and rebuild perf_priors.json; non-fatal.
if [[ "${FD_PERF_DAILY:-1}" != "0" ]]; then
    YESTERDAY=$(TZ=Asia/Shanghai date -d 'yesterday' +%F 2>/dev/null || TZ=Asia/Shanghai date -v-1d +%F)
    PERF_OUT=/workspace/x/perf/daily
    mkdir -p "$PERF_OUT"
    /workspace/fd_venv/bin/python scripts/perf_review.py --fetch --days "$YESTERDAY" --max-requests 45 --out "$PERF_OUT" \
        || echo "perf_review fetch failed (compose unaffected)"
    # Append/dedupe to rolling perf.jsonl (keyed by draft id, keep latest metrics)
    /workspace/fd_venv/bin/python - "$PERF_OUT/perf.jsonl" /workspace/x/perf/perf.jsonl <<'PY' || echo "perf append failed"
import json, sys
from pathlib import Path
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
if not src.exists():
    sys.exit(0)
dst.parent.mkdir(parents=True, exist_ok=True)
existing = {}
if dst.exists():
    for line in dst.read_text().splitlines():
        try:
            r = json.loads(line)
            if r.get('id'):
                existing[r['id']] = line
        except ValueError:
            pass
for line in src.read_text().splitlines():
    try:
        r = json.loads(line)
        if r.get('id'):
            existing[r['id']] = line
    except ValueError:
        pass
dst.write_text('\n'.join(existing.values()) + '\n' if existing else '')
print(f'perf.jsonl: {len(existing)} rows')
PY
    /workspace/fd_venv/bin/python scripts/perf_priors.py \
        --perf-jsonl /workspace/x/perf/perf.jsonl \
        --out live/store/feedback/perf_priors.json \
        || echo "perf_priors failed (compose unaffected)"
fi
BUDGET="${FD_DAILY_COMPOSE_BUDGET_USD:-25}"
# Oct 8 evening: whole-day ring fence (Fiona: total daily <= $25). Tonight's ingest spend (flashes, lane flashes, X,
# EXTRACT; summary /workspace/x/ingest_runs/<Beijing day>.json, written minutes ago by daily_ingest.sh) comes off the
# compose budget so ingest + compose stay <= FD_DAILY_TOTAL_USD. Missing / stale (> 3h) summary: no reduction.
BUDGET=$(/workspace/fd_venv/bin/python - "$BUDGET" "${FD_DAILY_TOTAL_USD:-25}" <<'PY' || echo "$BUDGET"
import json, sys, time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
budget, total = float(sys.argv[1]), float(sys.argv[2])
p = Path('/workspace/x/ingest_runs') / (datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d') + '.json')
spent = 0.0
if p.exists() and time.time() - p.stat().st_mtime < 3 * 3600:
    c = json.loads(p.read_text()).get('cost_usd') or {}
    spent = float(c.get('day_total', c.get('total')) or 0)   # day_total: all ingest runs of the day (reruns)
print(f'{max(0.5, min(budget, total - spent)):.2f}')
PY
)
echo "compose budget \$${BUDGET} (day total cap \$${FD_DAILY_TOTAL_USD:-25} minus tonight's ingest spend)"
# Calls served by subrouter are ledgered (provider=subrouter, tokens + nominal cost) but add $0 to the run budget and to
# the cumulative cap; only paid micuapi fallback calls (and ingest) count.
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
