#!/usr/bin/env bash
set -Eeuo pipefail

log()  { printf '\n[PANEL-STOP] %s\n' "$*"; }
warn() { printf '\n[WARN] %s\n' "$*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

BACKEND_PID_FILE="${PROJECT_DIR}/.panel-backend.pid"
FRONTEND_PID_FILE="${PROJECT_DIR}/.panel-frontend.pid"

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

stop_pid_file() {
  local name="$1"
  local pid_file="$2"
  local pid

  cleanup_stale_pid "$pid_file"
  pid="$(read_pid "$pid_file" 2>/dev/null || true)"

  if [[ -z "$pid" ]]; then
    log "$name déjà arrêté."
    return 0
  fi

  if is_pid_running "$pid"; then
    log "Arrêt de $name (PID $pid)..."
    kill "$pid" >/dev/null 2>&1 || true

    for _ in {1..10}; do
      if ! is_pid_running "$pid"; then
        break
      fi
      sleep 1
    done

    if is_pid_running "$pid"; then
      warn "$name ne s'arrête pas proprement, envoi de SIGKILL."
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  fi

  rm -f "$pid_file"
}

port_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser "${port}/tcp" 2>/dev/null || true
  fi
}

cmdline_for_pid() {
  local pid="$1"
  ps -p "$pid" -o args= 2>/dev/null || true
}

stop_panel_process_on_port() {
  local name="$1"
  local port="$2"
  local pid cmd

  while read -r pid; do
    [[ -n "$pid" ]] || continue
    cmd="$(cmdline_for_pid "$pid")"
    case "$cmd" in
      *"$PROJECT_DIR/ebpf_panel/app/backend"*"uvicorn"*)
        log "Arrêt du backend détecté sur le port $port (PID $pid)..."
        kill "$pid" >/dev/null 2>&1 || true
        ;;
      *"$PROJECT_DIR/ebpf_panel/app/frontend"*"vite"*|*"npm run dev -- --host 0.0.0.0 --port $port"*)
        log "Arrêt du frontend détecté sur le port $port (PID $pid)..."
        kill "$pid" >/dev/null 2>&1 || true
        ;;
      "")
        ;;
      *)
        warn "Le port $port est utilisé par un processus externe à ce lanceur : PID $pid ($cmd)"
        ;;
    esac
  done < <(port_pids "$port")

  sleep 1
}

check_port() {
  local port="$1"
  if [[ -n "$(port_pids "$port")" ]]; then
    warn "Le port $port est encore occupé."
    return 1
  fi
  log "Port $port libéré."
}

main() {
  stop_pid_file "backend" "$BACKEND_PID_FILE"
  stop_pid_file "frontend" "$FRONTEND_PID_FILE"

  stop_panel_process_on_port "backend" "$BACKEND_PORT"
  stop_panel_process_on_port "frontend" "$FRONTEND_PORT"

  check_port "$BACKEND_PORT" || true
  check_port "$FRONTEND_PORT" || true

  cat <<EOF

Panel arrêté.

- backend  : port ${BACKEND_PORT}
- frontend : port ${FRONTEND_PORT}

EOF
}

main "$@"
