#!/usr/bin/env bash
#
# run.sh — start the hibrid backend (engine API) and frontend (mobile web app)
# together for local development.
#
#   ./run.sh            start both, stream logs, Ctrl+C stops both
#   ./run.sh backend    start only the FastAPI engine on :8000
#   ./run.sh frontend   start only the Vite dev server
#
# Env overrides:
#   API_PORT      backend port (default 8000)
#   API_HOST      backend host (default 127.0.0.1)
#   VITE_API_URL  URL the frontend calls (default http://127.0.0.1:$API_PORT)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="$ROOT/hibrid-engine"
APP_DIR="$ROOT/hibrid-app"

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
export VITE_API_URL="${VITE_API_URL:-http://$API_HOST:$API_PORT}"

BLUE="\033[0;34m"; GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"
log() { printf "${BLUE}[run]${NC} %s\n" "$*"; }
ok()  { printf "${GREEN}[run]${NC} %s\n" "$*"; }
warn(){ printf "${YELLOW}[run]${NC} %s\n" "$*"; }
err() { printf "${RED}[run]${NC} %s\n" "$*" >&2; }

# ---------------------------------------------------------------------------
# Backend: FastAPI engine
# ---------------------------------------------------------------------------
setup_backend() {
  cd "$ENGINE_DIR"
  if [ ! -d ".venv" ]; then
    log "creating Python virtualenv (.venv)"
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  if ! python -c "import fastapi, uvicorn, hibrid.api.app" >/dev/null 2>&1; then
    log "installing backend dependencies (editable, [dev,api])"
    pip install -q -e ".[dev,api]"
  fi
  ok "backend ready"
}

run_backend() {
  cd "$ENGINE_DIR"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  ok "engine API -> http://$API_HOST:$API_PORT  (docs at /docs)"
  exec python -m uvicorn hibrid.api.app:app --host "$API_HOST" --port "$API_PORT" --reload
}

# ---------------------------------------------------------------------------
# Frontend: Vite dev server
# ---------------------------------------------------------------------------
pick_pm() {
  if command -v bun >/dev/null 2>&1; then echo "bun"; else echo "npm"; fi
}

setup_frontend() {
  cd "$APP_DIR"
  local pm; pm="$(pick_pm)"
  if [ ! -d "node_modules" ]; then
    log "installing frontend dependencies with $pm"
    if [ "$pm" = "bun" ]; then bun install; else npm install; fi
  fi
  ok "frontend ready (package manager: $pm)"
}

run_frontend() {
  cd "$APP_DIR"
  local pm; pm="$(pick_pm)"
  ok "web app -> Vite dev server (calling engine at $VITE_API_URL)"
  if [ "$pm" = "bun" ]; then exec bun run dev; else exec npm run dev; fi
}

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
case "${1:-all}" in
  backend)
    setup_backend; run_backend ;;
  frontend)
    setup_frontend; run_frontend ;;
  all|"")
    setup_backend
    setup_frontend

    pids=()
    cleanup() {
      warn "shutting down..."
      for pid in "${pids[@]:-}"; do
        kill "$pid" >/dev/null 2>&1 || true
      done
      wait >/dev/null 2>&1 || true
      exit 0
    }
    trap cleanup INT TERM

    ( run_backend 2>&1 | sed "s/^/$(printf "${GREEN}[api]${NC} ")/" ) &
    pids+=($!)

    # Give the engine a moment so the first frontend request lands warm.
    sleep 2

    ( run_frontend 2>&1 | sed "s/^/$(printf "${BLUE}[web]${NC} ")/" ) &
    pids+=($!)

    ok "both running — press Ctrl+C to stop"
    wait ;;
  *)
    err "unknown target '${1}'. Use: backend | frontend | all"
    exit 1 ;;
esac
