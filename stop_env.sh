#!/usr/bin/env bash
set -Eeuo pipefail

#------------------------------------------------------------------------------
# Arrêt propre de l'environnement eBPF + N8N + Ollama + Web labo + DNS
#
# - Stoppe les conteneurs n8n, ollama, web-lab et dns-lab s'ils tournent
# - Détache la sonde XDP si elle est attachée
# - Ne supprime rien
# - Ne réactive PAS systemd-resolved (il reste dans l'état laissé par setup)
#------------------------------------------------------------------------------

log()  { printf "\n[STOP] %s\n" "$*"; }
warn() { printf "\n[WARN] %s\n" "$*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

N8N_CONTAINER="${N8N_CONTAINER:-n8n}"
OLLAMA_CONTAINER="${OLLAMA_CONTAINER:-ollama}"
WEB_CONTAINER="${WEB_CONTAINER:-web-lab}"
DNS_CONTAINER="${DNS_CONTAINER:-dns-lab}"

detect_iface() {
  local iface
  iface="$(ip route get 1.1.1.1 2>/dev/null | awk '/dev/ {for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')"
  printf '%s\n' "${iface:-}"
}

container_running() {
  docker ps --format '{{.Names}}' | grep -Fxq "$1"
}

container_exists() {
  docker ps -a --format '{{.Names}}' | grep -Fxq "$1"
}

# Arrête ET supprime le conteneur - les volumes Docker restent intacts,
# les données (modèles Ollama, workflows n8n, rapports) sont préservées.
stop_and_remove_container() {
  local name="$1"
  if container_running "$name"; then
    log "Arrêt du conteneur '$name'..."
    docker stop "$name" >/dev/null || warn "Impossible d'arrêter '$name'."
  fi
  if container_exists "$name"; then
    log "Suppression du conteneur '$name' (volumes préservés)..."
    docker rm "$name" >/dev/null || warn "Impossible de supprimer '$name'."
  else
    log "Conteneur '$name' absent."
  fi
}

detach_xdp_if_present() {
  local iface="$1"
  [[ -n "$iface" ]] || {
    warn "Interface réseau non détectée, détachement XDP ignoré."
    return 0
  }

  if ip -details link show dev "$iface" 2>/dev/null | grep -q "prog/xdp"; then
    log "Sonde XDP détectée sur '$iface', détachement..."
    sudo ip link set dev "$iface" xdpgeneric off 2>/dev/null || true
    sudo ip link set dev "$iface" xdp off 2>/dev/null || true
    log "Sonde XDP détachée de '$iface'."
  else
    log "Aucune sonde XDP détectée sur '$iface'."
  fi
}

main() {
  log "Arrêt de l'environnement du projet : $PROJECT_DIR"

  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker n'est pas installé ou pas dans le PATH. Arrêt des conteneurs ignoré."
  else
    stop_and_remove_container "$N8N_CONTAINER"
    stop_and_remove_container "$OLLAMA_CONTAINER"
    stop_and_remove_container "$WEB_CONTAINER"
    stop_and_remove_container "$DNS_CONTAINER"
  fi

  if command -v ip >/dev/null 2>&1; then
    IFACE="${IFACE:-$(detect_iface)}"
    detach_xdp_if_present "$IFACE"
  else
    warn "Commande 'ip' absente, détachement XDP ignoré."
  fi

  log "Arrêt terminé."
  cat <<EOF

Conteneurs supprimés (recréés proprement au prochain setup).
Données préservées :
- modèles Ollama    : volume ollama_data
- workflows N8N     : volume n8n_data
- rapports          : $PROJECT_DIR/rapports
- fichiers web-lab  : $PROJECT_DIR/web-lab/nginx
- fichiers dns-lab  : $PROJECT_DIR/dns-lab

Note : si systemd-resolved a été modifié par setup_env.sh,
il reste dans cet état (DNSStubListener=no).

Pour redémarrer :
  ./setup_env.sh

EOF
}

main "$@"
