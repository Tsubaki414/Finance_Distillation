# Sourced (not executed) by daily_ingest.sh, daily_compose.sh, midday_compose.sh and engage_pull.sh.
# Oct 13 07:37 London (Fiona): official Gemini (GEMINI_API_KEY) is the primary provider for every scheduled FD run;
# subrouter is only a provider fallback (live/stage_models._official_subrouter_fallback; a 402 kills it for the day).
# Non-secret settings: ${FD_PROVIDER_ENV:-~/.config/fd/provider.env}; key: ${FD_GEMINI_ENV:-~/.secrets/gemini.env}
# (chmod 600, never printed). Variables already set in the environment win.
_fd_load_env() {
    local f="$1" k v
    [[ -r "$f" ]] || return 0
    while IFS='=' read -r k v; do
        [[ "$k" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
        [[ -n "${!k:-}" ]] && continue
        v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
        export "$k=$v"
    done < "$f"
}
_fd_load_env "${FD_PROVIDER_ENV:-$HOME/.config/fd/provider.env}"
_fd_load_env "${FD_GEMINI_ENV:-$HOME/.secrets/gemini.env}"
if [[ -n "${GEMINI_API_KEY:-}" ]]; then echo "key GEMINI_API_KEY: set"; else echo "key GEMINI_API_KEY: missing"; fi
echo "FD_GEMINI_PROVIDER=${FD_GEMINI_PROVIDER:-unset}"
unset -f _fd_load_env
