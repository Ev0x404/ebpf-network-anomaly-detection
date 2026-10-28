#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPORTS_DIR="$PROJECT_DIR/rapports"

DOCKER_NETWORK="${DOCKER_NETWORK:-ebpf-net}"

N8N_CONTAINER="${N8N_CONTAINER:-n8n}"
N8N_IMAGE="${N8N_IMAGE:-docker.n8n.io/n8nio/n8n}"
N8N_VOLUME="${N8N_VOLUME:-n8n_data}"
N8N_PORT="${N8N_PORT:-5678}"

OLLAMA_CONTAINER="${OLLAMA_CONTAINER:-ollama}"
OLLAMA_IMAGE="${OLLAMA_IMAGE:-ollama/ollama}"
OLLAMA_VOLUME="${OLLAMA_VOLUME:-ollama_data}"
OLLAMA_MODEL="${OLLAMA_MODEL:-gemma3:4b}"

WEB_CONTAINER="${WEB_CONTAINER:-web-lab}"
WEB_IMAGE="${WEB_IMAGE:-nginx:latest}"
WEB_HTTP_PORT="${WEB_HTTP_PORT:-80}"
WEB_HTTPS_PORT="${WEB_HTTPS_PORT:-443}"
WEB_ROOT="${WEB_ROOT:-$PROJECT_DIR/web-lab/nginx}"
WEB_HTML_DIR="${WEB_HTML_DIR:-$WEB_ROOT/html}"
WEB_CONF_DIR="${WEB_CONF_DIR:-$WEB_ROOT/conf}"
WEB_CERTS_DIR="${WEB_CERTS_DIR:-$WEB_ROOT/certs}"
WEB_CERT_DAYS="${WEB_CERT_DAYS:-365}"

DNS_CONTAINER="${DNS_CONTAINER:-dns-lab}"
DNS_IMAGE="${DNS_IMAGE:-4km3/dnsmasq}"
DNS_PORT="${DNS_PORT:-53}"

ALERTS_LOG="${ALERTS_LOG:-$PROJECT_DIR/logs/alerts_local.jsonl}"
WORKFLOW_FILE="${WORKFLOW_FILE:-$PROJECT_DIR/scripts/n8n_workflow.json}"
WORKFLOW_MARKER="/home/node/.n8n/.bootstrap_workflow_imported"

GECKO_VERSION="${GECKO_VERSION:-v0.36.0}"

log(){ printf '\n[SETUP] %s\n' "$*"; }
warn(){ printf '\n[WARN] %s\n' "$*" >&2; }
die(){ printf '\n[ERREUR] %s\n' "$*" >&2; exit 1; }
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Commande manquante : $1"; }

run_sudo(){ if command -v sudo >/dev/null 2>&1; then sudo "$@"; else "$@"; fi; }

apt_install_if_missing(){
  local pkg missing=()
  for pkg in "$@"; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
  done
  if ((${#missing[@]})); then
    log "Installation paquets APT : ${missing[*]}"
    run_sudo apt-get update -y
    run_sudo apt-get install -y "${missing[@]}"
  fi
}

ensure_base_packages(){
  if command -v apt-get >/dev/null 2>&1; then
    apt_install_if_missing curl wget jq unzip ca-certificates gnupg lsb-release \
      python3 python3-venv python3-pip iproute2 make clang llvm libelf-dev \
      firefox openssl apache2-utils
  else
    warn "apt-get absent : installation automatique des dépendances système ignorée."
  fi
}

ensure_python_env(){
  local venv_dir="$PROJECT_DIR/.venv"
  if [[ ! -d "$venv_dir" ]]; then
    log "Creation du venv Python..."
    python3 -m venv "$venv_dir"
  fi
  # shellcheck disable=SC1091
  source "$venv_dir/bin/activate"
  python3 -m pip install --upgrade pip wheel setuptools
  python3 -m pip install -r "$PROJECT_DIR/requirements_training.txt"
}

ensure_geckodriver(){
  if command -v geckodriver >/dev/null 2>&1; then
    log "geckodriver déjà présent : $(command -v geckodriver)"
    return 0
  fi

  local arch suffix url tmpdir
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) suffix="linux64" ;;
    aarch64|arm64) suffix="linux-aarch64" ;;
    *) die "Architecture non supportée pour geckodriver : $arch" ;;
  esac

  tmpdir="$(mktemp -d)"
  url="https://github.com/mozilla/geckodriver/releases/download/${GECKO_VERSION}/geckodriver-${GECKO_VERSION}-${suffix}.tar.gz"
  log "Téléchargement de geckodriver ${GECKO_VERSION} (${suffix})..."
  curl -fsSL "$url" -o "$tmpdir/geckodriver.tar.gz"
  tar -xzf "$tmpdir/geckodriver.tar.gz" -C "$tmpdir"
  run_sudo install -m 0755 "$tmpdir/geckodriver" /usr/local/bin/geckodriver
  rm -rf "$tmpdir"
  log "geckodriver installé : $(command -v geckodriver)"
}

ensure_docker(){
  if command -v docker >/dev/null 2>&1; then
    log "Docker déjà installé."
  else
    log "Installation de Docker via script officiel..."
    curl -fsSL https://get.docker.com | run_sudo sh
  fi

  if command -v systemctl >/dev/null 2>&1; then
    run_sudo systemctl enable --now docker >/dev/null 2>&1 || true
  fi

  if ! docker info >/dev/null 2>&1; then
    warn "Accès Docker direct indisponible. Tentative avec sudo."
    if run_sudo docker info >/dev/null 2>&1; then
      DOCKER="sudo docker"
    else
      die "Docker installé mais non utilisable."
    fi
  else
    DOCKER="docker"
  fi
}

docker_container_exists(){ $DOCKER ps -a --format '{{.Names}}' | grep -Fxq "$1"; }
docker_container_running(){ $DOCKER ps --format '{{.Names}}' | grep -Fxq "$1"; }

ensure_network(){
  if $DOCKER network inspect "$DOCKER_NETWORK" >/dev/null 2>&1; then
    log "Réseau Docker '$DOCKER_NETWORK' déjà présent."
  else
    log "Création du réseau Docker '$DOCKER_NETWORK'..."
    $DOCKER network create "$DOCKER_NETWORK" >/dev/null
  fi
}

ensure_reports_dir(){
  mkdir -p "$REPORTS_DIR"
  chmod 777 "$REPORTS_DIR" || true
}

ensure_web_lab_files(){
  mkdir -p "$WEB_HTML_DIR" "$WEB_CONF_DIR" "$WEB_CERTS_DIR"

  if [[ ! -f "$WEB_HTML_DIR/index.html" ]]; then
    log "Création de la page HTML du labo web..."
    cat > "$WEB_HTML_DIR/index.html" <<'EOF'
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Serveur de labo eBPF</title>
</head>
<body>
  <h1>Serveur de labo eBPF + IA</h1>
  <p>Page locale pour l'entraînement HTTP/HTTPS.</p>
</body>
</html>
EOF
  fi

  log "Écriture / mise à jour de la configuration Nginx du labo..."
  cat > "$WEB_CONF_DIR/default.conf" <<'EOF'
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}

server {
    listen 443 ssl;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    ssl_certificate     /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF

  if [[ ! -f "$WEB_CERTS_DIR/server.crt" || ! -f "$WEB_CERTS_DIR/server.key" ]]; then
    log "Génération du certificat auto-signé du labo web..."
    openssl req -x509 -nodes -days "$WEB_CERT_DAYS" \
      -newkey rsa:2048 \
      -keyout "$WEB_CERTS_DIR/server.key" \
      -out "$WEB_CERTS_DIR/server.crt" \
      -subj "/C=FR/ST=Lab/L=Lab/O=Projet/CN=localhost" >/dev/null 2>&1
  else
    log "Certificat auto-signé déjà présent."
  fi
}

ensure_ollama_container(){
  # Si le conteneur existe mais n'est pas sur le bon réseau, on le supprime
  # pour le recréer proprement. Le volume préserve les modèles téléchargés.
  if docker_container_exists "$OLLAMA_CONTAINER"; then
    if ! $DOCKER inspect "$OLLAMA_CONTAINER" --format '{{json .NetworkSettings.Networks}}' | grep -q "\"$DOCKER_NETWORK\""; then
      log "Conteneur Ollama hors réseau '$DOCKER_NETWORK' - recréation propre..."
      $DOCKER rm -f "$OLLAMA_CONTAINER" >/dev/null
    fi
  fi

  if docker_container_exists "$OLLAMA_CONTAINER"; then
    if docker_container_running "$OLLAMA_CONTAINER"; then
      log "Conteneur Ollama '$OLLAMA_CONTAINER' déjà démarré."
    else
      log "Démarrage du conteneur Ollama '$OLLAMA_CONTAINER'..."
      $DOCKER start "$OLLAMA_CONTAINER" >/dev/null
    fi
  else
    log "Création du conteneur Ollama '$OLLAMA_CONTAINER'..."
    $DOCKER run -d \
      --name "$OLLAMA_CONTAINER" \
      --network "$DOCKER_NETWORK" \
      -v "${OLLAMA_VOLUME}:/root/.ollama" \
      "$OLLAMA_IMAGE" >/dev/null
  fi
}

ensure_n8n_container(){
  local recreate=0

  if docker_container_exists "$N8N_CONTAINER"; then
    if ! $DOCKER inspect "$N8N_CONTAINER" --format '{{json .Mounts}}' | grep -q '/home/node/.n8n-files/rapports'; then
      recreate=1
    fi
    if ! $DOCKER inspect "$N8N_CONTAINER" --format '{{json .Config.Env}}' | grep -q 'N8N_RESTRICT_FILE_ACCESS_TO=/home/node/.n8n-files/rapports;/tmp;/home/node/.n8n'; then
      recreate=1
    fi
  fi

  if ((recreate)); then
    log "Recréation du conteneur N8N pour appliquer la bonne configuration des rapports..."
    $DOCKER rm -f "$N8N_CONTAINER" >/dev/null 2>&1 || true
  fi

  if docker_container_exists "$N8N_CONTAINER"; then
    if docker_container_running "$N8N_CONTAINER"; then
      log "Conteneur N8N '$N8N_CONTAINER' déjà démarré."
    else
      log "Démarrage du conteneur N8N '$N8N_CONTAINER'..."
      $DOCKER start "$N8N_CONTAINER" >/dev/null
    fi
  else
    log "Création du conteneur N8N '$N8N_CONTAINER'..."
    $DOCKER run -d \
      --name "$N8N_CONTAINER" \
      --network "$DOCKER_NETWORK" \
      -p "${N8N_PORT}:5678" \
      -e N8N_RESTRICT_FILE_ACCESS_TO="/home/node/.n8n-files/rapports;/tmp;/home/node/.n8n" \
      -v "${N8N_VOLUME}:/home/node/.n8n" \
      -v "${PROJECT_DIR}/scripts:/project_bootstrap:ro" \
      -v "${PROJECT_DIR}/rapports:/home/node/.n8n-files/rapports" \
      "$N8N_IMAGE" >/dev/null
  fi

  if ! $DOCKER inspect "$N8N_CONTAINER" --format '{{json .NetworkSettings.Networks}}' | grep -q "\"$DOCKER_NETWORK\""; then
    $DOCKER network connect "$DOCKER_NETWORK" "$N8N_CONTAINER" >/dev/null 2>&1 || true
  fi
}

ensure_web_lab_container(){
  if docker_container_exists "$WEB_CONTAINER"; then
    if docker_container_running "$WEB_CONTAINER"; then
      log "Conteneur web de labo '$WEB_CONTAINER' déjà démarré."
    else
      log "Démarrage du conteneur web de labo '$WEB_CONTAINER'..."
      $DOCKER start "$WEB_CONTAINER" >/dev/null
    fi
  else
    log "Création du conteneur web de labo '$WEB_CONTAINER'..."
    $DOCKER run -d \
      --name "$WEB_CONTAINER" \
      --restart unless-stopped \
      --network "$DOCKER_NETWORK" \
      -p "${WEB_HTTP_PORT}:80" \
      -p "${WEB_HTTPS_PORT}:443" \
      -v "${WEB_HTML_DIR}:/usr/share/nginx/html:ro" \
      -v "${WEB_CONF_DIR}/default.conf:/etc/nginx/conf.d/default.conf:ro" \
      -v "${WEB_CERTS_DIR}:/etc/nginx/certs:ro" \
      "$WEB_IMAGE" >/dev/null
  fi

  if ! $DOCKER inspect "$WEB_CONTAINER" --format '{{json .NetworkSettings.Networks}}' | grep -q "\"$DOCKER_NETWORK\""; then
    $DOCKER network connect "$DOCKER_NETWORK" "$WEB_CONTAINER" >/dev/null 2>&1 || true
  fi
}

# -- Vérifie si le port 53 UDP est libre sur toutes les interfaces ----------
port53_is_free(){
  ! run_sudo ss -ulnp 2>/dev/null | grep -q ':53 '
}

# -- Désactive uniquement le stub listener de systemd-resolved ----------
# Le service reste actif - seul le port 53 est libéré.
# Fallback : stop/disable complet si le stub reste malgré tout.
free_port53_from_systemd_resolved(){
  log "Désactivation du stub listener systemd-resolved (service conservé)..."
  run_sudo mkdir -p /etc/systemd/resolved.conf.d
  printf '[Resolve]\nDNSStubListener=no\n' \
    | run_sudo tee /etc/systemd/resolved.conf.d/no-stub.conf > /dev/null
  run_sudo systemctl restart systemd-resolved
  sleep 2

  if port53_is_free; then
    log "Stub listener désactivé - systemd-resolved toujours actif pour la résolution DNS de la VM."
    return 0
  fi

  # Fallback : arrêt complet si DNSStubListener=no n'a pas suffi
  warn "Stub listener toujours présent - arrêt complet de systemd-resolved..."
  run_sudo systemctl stop systemd-resolved
  run_sudo systemctl disable systemd-resolved
  if [[ -L /etc/resolv.conf ]]; then
    run_sudo rm -f /etc/resolv.conf
    printf 'nameserver 8.8.8.8\nnameserver 1.1.1.1\n' \
      | run_sudo tee /etc/resolv.conf > /dev/null
    log "resolv.conf recréé avec 8.8.8.8 / 1.1.1.1 (fallback)"
  fi
}

ensure_dns_container(){
  log "Configuration du serveur DNS (conteneur dnsmasq) pour la capture XDP..."

  if port53_is_free; then
    log "Port 53 libre - aucune modification de systemd-resolved nécessaire."
  else
    local occupant
    occupant="$(run_sudo ss -ulnp 2>/dev/null | grep ':53 ' || true)"

    if echo "$occupant" | grep -q 'systemd-resolve\|systemd-r'; then
      free_port53_from_systemd_resolved
    elif echo "$occupant" | grep -q "$DNS_CONTAINER\|dnsmasq"; then
      log "Port 53 déjà tenu par le conteneur DNS - rien à faire."
    else
      warn "Port 53 occupé par un processus inconnu - le conteneur risque d'échouer :"
      echo "$occupant" >&2
    fi
  fi

  # Config dnsmasq pour le conteneur
  mkdir -p "$PROJECT_DIR/dns-lab"
  cat > "$PROJECT_DIR/dns-lab/dnsmasq.conf" <<'DNSCONF'
# Lab eBPF - résolveur récursif minimal
port=53
bind-interfaces
no-resolv
server=8.8.8.8
server=1.1.1.1
cache-size=500
DNSCONF

  if docker_container_exists "$DNS_CONTAINER"; then
    if docker_container_running "$DNS_CONTAINER"; then
      log "Conteneur DNS '$DNS_CONTAINER' déjà démarré."
    else
      log "Démarrage du conteneur DNS '$DNS_CONTAINER'..."
      $DOCKER start "$DNS_CONTAINER" >/dev/null
    fi
  else
    log "Création du conteneur DNS '$DNS_CONTAINER' (strm/dnsmasq)..."
    $DOCKER run -d \
      --name "$DNS_CONTAINER" \
      --restart unless-stopped \
      --network "$DOCKER_NETWORK" \
      -p "${DNS_PORT}:53/udp" \
      -p "${DNS_PORT}:53/tcp" \
      --cap-add NET_ADMIN \
      -v "$PROJECT_DIR/dns-lab/dnsmasq.conf:/etc/dnsmasq.conf:ro" \
      "$DNS_IMAGE" >/dev/null
  fi

  if ! $DOCKER inspect "$DNS_CONTAINER" --format '{{json .NetworkSettings.Networks}}' | grep -q "\"$DOCKER_NETWORK\""; then
    $DOCKER network connect "$DOCKER_NETWORK" "$DNS_CONTAINER" >/dev/null 2>&1 || true
  fi

  # Attente que le port 53 réponde
  local i
  for i in {1..15}; do
    if run_sudo ss -ulnp 2>/dev/null | grep -q ':53 '; then
      log "Conteneur DNS écoute sur le port 53 UDP."
      return 0
    fi
    sleep 1
  done
  warn "Conteneur DNS démarré mais port 53 non détecté - vérifier : sudo ss -ulnp | grep 53"
}

# -- Vérifie que la résolution DNS de la VM est opérationnelle ------------
check_dns_resolution(){
  log "Vérification de la résolution DNS de la VM..."
  local ok=0

  if command -v dig >/dev/null 2>&1; then
    if dig +short +time=3 google.com A @8.8.8.8 | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
      log "  [OK] dig google.com @8.8.8.8 → résolution directe fonctionnelle"
      ok=1
    fi
    if dig +short +time=3 google.com A | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
      log "  [OK] dig google.com (résolveur système) → résolution fonctionnelle"
    else
      warn "  [WARN] dig google.com via résolveur système a échoué - vérifier /etc/resolv.conf"
    fi
  fi

  if command -v curl >/dev/null 2>&1; then
    if curl -fsSL --max-time 5 https://google.com -o /dev/null 2>/dev/null; then
      log "  [OK] curl https://google.com → réseau + DNS + TLS fonctionnels"
      ok=1
    fi
  fi

  if ((ok == 0)); then
    warn "Résolution DNS de la VM potentiellement dégradée - vérifier manuellement : dig google.com"
  fi
}

wait_http(){
  local url="$1" name="$2" insecure="${3:-0}" i curl_args=()
  if [[ "$insecure" == "1" ]]; then
    curl_args=(-k)
  fi
  for i in {1..45}; do
    if curl -fsS "${curl_args[@]}" "$url" >/dev/null 2>&1; then
      log "$name répond sur $url"
      return 0
    fi
    sleep 1
  done
  warn "$name ne répond pas encore sur $url"
  return 1
}

ensure_ollama_model(){
  log "Vérification du modèle Ollama '$OLLAMA_MODEL'..."
  if $DOCKER exec "$OLLAMA_CONTAINER" ollama list 2>/dev/null | awk '{print $1}' | grep -Fxq "$OLLAMA_MODEL"; then
    log "Modèle '$OLLAMA_MODEL' déjà présent dans le conteneur."
  else
    log "Téléchargement du modèle '$OLLAMA_MODEL' dans le conteneur Ollama..."
    $DOCKER exec -i "$OLLAMA_CONTAINER" ollama pull "$OLLAMA_MODEL"
  fi
}

import_n8n_workflow(){
  [[ -f "$WORKFLOW_FILE" ]] || { warn "Workflow N8N introuvable : $WORKFLOW_FILE"; return 0; }
  if $DOCKER exec "$N8N_CONTAINER" sh -lc "test -f '$WORKFLOW_MARKER'" >/dev/null 2>&1; then
    log "Workflow N8N déjà importé précédemment."
    return 0
  fi

  log "Import du workflow N8N par défaut..."
  if $DOCKER exec "$N8N_CONTAINER" sh -lc "n8n import:workflow --input=/project_bootstrap/$(basename "$WORKFLOW_FILE") && touch '$WORKFLOW_MARKER'"; then
    log "Workflow N8N importé."
  else
    warn "Import automatique du workflow N8N impossible. Le fichier reste disponible dans scripts/n8n_workflow.json pour import manuel."
  fi
}

find_xdp_obj(){
  local candidate
  candidate="$(find "$PROJECT_DIR/ebpf" -type f \( -name 'xdp_monitor.bpf.o' -o -name '*xdp*.bpf.o' \) 2>/dev/null | head -n 1 || true)"
  [[ -n "$candidate" ]] && printf '%s\n' "$candidate"
}

detect_iface(){
  local iface
  iface="$(ip route get 1.1.1.1 2>/dev/null | awk '/dev/ {for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')"
  [[ -n "${iface:-}" ]] || die "Impossible de détecter l'interface réseau."
  printf '%s\n' "$iface"
}

ensure_xdp_artifact(){
  local xdp_obj="$1"
  if [[ -f "$xdp_obj" ]]; then
    return 0
  fi
  log "Objet XDP absent, tentative de compilation..."
  (cd "$PROJECT_DIR/ebpf" && make) || die "Compilation XDP échouée."
  [[ -f "$xdp_obj" ]] || die "Objet XDP introuvable après compilation : $xdp_obj"
}

reset_xdp(){
  local iface="$1" xdp_obj="$2"
  [[ -f "$xdp_obj" ]] || die "Objet XDP introuvable : $xdp_obj"
  log "Réinitialisation XDP sur l'interface '$iface'..."
  run_sudo ip link set dev "$iface" xdpgeneric off 2>/dev/null || true
  run_sudo ip link set dev "$iface" xdp off 2>/dev/null || true
  log "Réattachement de la sonde XDP : $xdp_obj"
  run_sudo ip link set dev "$iface" xdpgeneric obj "$xdp_obj" sec xdp
  log "État XDP actuel :"
  ip -details link show dev "$iface" | sed -n '1,8p'
}

clean_temp_logs(){
  mkdir -p "$(dirname "$ALERTS_LOG")"
  : > "$ALERTS_LOG"
}

show_summary(){
  cat <<EOF

[OK] Préparation terminée.

Rappels :
- Entraînement Isolation Forest conservé : $PROJECT_DIR/models
- Volume N8N conservé                    : $N8N_VOLUME
- Volume Ollama conservé                 : $OLLAMA_VOLUME
- Réseau Docker                          : $DOCKER_NETWORK
- Modèle Ollama attendu                  : $OLLAMA_MODEL
- URL Ollama dans N8N                    : http://ollama:11434/api/generate
- Web labo HTTP                          : http://localhost:${WEB_HTTP_PORT}
- Web labo HTTPS                         : https://localhost:${WEB_HTTPS_PORT}  (certificat auto-signé)
- Serveur DNS                            : udp://localhost:${DNS_PORT}  (dnsmasq conteneur dns-lab)

EOF
}

main(){
  ensure_base_packages
  ensure_python_env
  ensure_geckodriver
  ensure_docker
  ensure_network
  ensure_reports_dir
  ensure_web_lab_files
  ensure_ollama_container
  ensure_n8n_container
  ensure_web_lab_container
  ensure_dns_container
  check_dns_resolution

  log "Conteneurs Docker actifs :"
  $DOCKER ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

  ensure_ollama_model
  wait_http "http://localhost:${N8N_PORT}" "N8N" || true
  wait_http "http://localhost:${WEB_HTTP_PORT}" "Web labo HTTP" || true
  wait_http "https://localhost:${WEB_HTTPS_PORT}" "Web labo HTTPS" 1 || true
  import_n8n_workflow

  clean_temp_logs

  local xdp_obj iface
  xdp_obj="${XDP_OBJ:-$(find_xdp_obj || true)}"
  [[ -n "${xdp_obj:-}" ]] || die "Impossible de trouver automatiquement le fichier .bpf.o dans $PROJECT_DIR/ebpf"
  ensure_xdp_artifact "$xdp_obj"
  iface="${IFACE:-$(detect_iface)}"
  log "Interface détectée : $iface"
  log "Objet XDP détecté : $xdp_obj"
  reset_xdp "$iface" "$xdp_obj"

  log "Vérification rapide du réseau Docker des conteneurs..."
  $DOCKER inspect "$N8N_CONTAINER" --format '{{json .NetworkSettings.Networks}}'
  $DOCKER inspect "$OLLAMA_CONTAINER" --format '{{json .NetworkSettings.Networks}}'
  $DOCKER inspect "$WEB_CONTAINER" --format '{{json .NetworkSettings.Networks}}'
  $DOCKER inspect "$DNS_CONTAINER" --format '{{json .NetworkSettings.Networks}}'

  show_summary
}

main "$@"
