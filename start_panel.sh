#!/usr/bin/env bash
set -Eeuo pipefail

log()  { printf '\n[PANEL] %s\n' "$*"; }
warn() { printf '\n[WARN] %s\n' "$*" >&2; }
die()  { printf '\n[ERREUR] %s\n' "$*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
BACKEND_DIR="$PROJECT_DIR/ebpf_panel/app/backend"
FRONTEND_DIR="$PROJECT_DIR/ebpf_panel/app/frontend"

BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

BACKEND_LOG="${PROJECT_DIR}/logs/panel-backend.log"
FRONTEND_LOG="${PROJECT_DIR}/logs/panel-frontend.log"
BACKEND_PID_FILE="${PROJECT_DIR}/.panel-backend.pid"
FRONTEND_PID_FILE="${PROJECT_DIR}/.panel-frontend.pid"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Commande manquante : $1"
}

is_pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

read_pid() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  tr -d '[:space:]' < "$pid_file"
}

cleanup_stale_pid() {
  local pid_file="$1"
  local pid
  pid="$(read_pid "$pid_file" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 0
  if ! is_pid_running "$pid"; then
    rm -f "$pid_file"
  fi
}

wait_http() {
  local name="$1"
  local url="$2"
  local attempts="${3:-30}"
  local i

  for ((i = 1; i <= attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "$name prêt sur $url"
      return 0
    fi
    sleep 1
  done

  warn "$name ne répond pas encore sur $url. Vérifie les logs."
  return 1
}

start_backend() {
  local pid

  cleanup_stale_pid "$BACKEND_PID_FILE"
  pid="$(read_pid "$BACKEND_PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && is_pid_running "$pid"; then
    log "Backend déjà lancé (PID $pid)."
    return 0
  fi

  local venv_uvicorn="$PROJECT_DIR/.venv/bin/uvicorn"
  [[ -x "$venv_uvicorn" ]] || die "uvicorn introuvable dans le venv racine : $PROJECT_DIR/.venv"

  log "Démarrage du backend du panel..."
  (
    cd "$BACKEND_DIR"
    nohup "$venv_uvicorn" \
      app.main:app \
      --host 0.0.0.0 \
      --port "$BACKEND_PORT" \
      >"$BACKEND_LOG" 2>&1 &
    echo "$!" > "$BACKEND_PID_FILE"
  )
}

start_frontend() {
  local pid

  cleanup_stale_pid "$FRONTEND_PID_FILE"
  pid="$(read_pid "$FRONTEND_PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && is_pid_running "$pid"; then
    log "Frontend déjà lancé (PID $pid)."
    return 0
  fi

  [[ -d "$FRONTEND_DIR/node_modules" ]] || die "Dépendances frontend introuvables : $FRONTEND_DIR/node_modules"

  log "Démarrage du frontend du panel..."
  (
    cd "$FRONTEND_DIR"
    nohup npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" >"$FRONTEND_LOG" 2>&1 &
    echo "$!" > "$FRONTEND_PID_FILE"
  )
}

main() {
  need_cmd curl
  need_cmd npm

  mkdir -p "$PROJECT_DIR/logs"

  start_backend
  wait_http "Backend" "http://127.0.0.1:${BACKEND_PORT}/api/health" 30 || true

  start_frontend
  wait_http "Frontend" "http://127.0.0.1:${FRONTEND_PORT}" 30 || true

  cat <<EOF

Panel lancé.

- Frontend : http://localhost:${FRONTEND_PORT}
- Backend  : http://localhost:${BACKEND_PORT}

Logs :
- $BACKEND_LOG
- $FRONTEND_LOG

PID :
- backend  : $BACKEND_PID_FILE
- frontend : $FRONTEND_PID_FILE

EOF
}

main "$@"
