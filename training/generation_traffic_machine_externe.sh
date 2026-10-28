#!/usr/bin/env bash

set -Eeuo pipefail

TARGET="${1:?Usage: $0 <IP_VM> <utilisateur_ssh> [duree_en_minutes]}"
SSH_USER="${2:?Usage: $0 <IP_VM> <utilisateur_ssh> [duree_en_minutes]}"
DURATION_MIN="${3:-18}"

DNS_SERVER="${DNS_SERVER:-$TARGET}"
HTTP_PORT="${HTTP_PORT:-80}"
HTTPS_PORT="${HTTPS_PORT:-443}"
SSH_PORT="${SSH_PORT:-22}"
INCLUDE_SSH_FAILURES="${INCLUDE_SSH_FAILURES:-0}"

PAUSE_SHORT_MIN=1; PAUSE_SHORT_MAX=4
PAUSE_MED_MIN=5;   PAUSE_MED_MAX=12
PAUSE_LONG_MIN=13; PAUSE_LONG_MAX=28
WEB_MIN=3; WEB_MAX=7; WEB_SLEEP_MIN=1; WEB_SLEEP_MAX=8
DNS_MIN=4; DNS_MAX=10; DNS_SLEEP_MIN=1; DNS_SLEEP_MAX=7
SSH_MIN=3; SSH_MAX=5; SSH_SLEEP_MIN=3; SSH_SLEEP_MAX=9
APT_MIN=1; APT_MAX=3; APT_SLEEP_MIN=3; APT_SLEEP_MAX=9

END_TS=$(( $(date +%s) + DURATION_MIN * 60 ))
ACTION_COUNT=0

HTTP_BASE="http://${TARGET}:${HTTP_PORT}"
HTTPS_BASE="https://${TARGET}:${HTTPS_PORT}"

log()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
ok()   { printf '[OK] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
err()  { printf '[ERR] %s\n' "$*" >&2; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    err "Commande manquante: $1"
    exit 1
  }
}

rand_between() {
  local min="$1"
  local max="$2"
  echo $(( min + RANDOM % (max - min + 1) ))
}

weighted_sleep() {
  # Pauses humaines: beaucoup de petites pauses, parfois une vraie lecture.
  local roll pause
  roll=$((RANDOM % 100))
  if (( roll < 55 )); then
    pause="$(rand_between "$PAUSE_SHORT_MIN" "$PAUSE_SHORT_MAX")"
  elif (( roll < 85 )); then
    pause="$(rand_between "$PAUSE_MED_MIN" "$PAUSE_MED_MAX")"
  else
    pause="$(rand_between "$PAUSE_LONG_MIN" "$PAUSE_LONG_MAX")"
  fi
  sleep "$pause"
}

short_pause() {
  sleep "$(rand_between 1 5)"
}

still_running() {
  (( $(date +%s) < END_TS ))
}

user_agent() {
  local agents=(
    "Mozilla/5.0 (X11; Linux x86_64; rv:115.0) Gecko/20100101 Firefox/115.0"
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121.0 Safari/537.36"
    "curl/8.5.0"
  )
  echo "${agents[$((RANDOM % ${#agents[@]}))]}"
}

curl_common() {
  curl -sS -L \
    --connect-timeout 4 \
    --max-time "$(rand_between 6 18)" \
    --retry 0 \
    -A "$(user_agent)" \
    -H "Accept-Language: fr-FR,fr;q=0.9,en;q=0.7" \
    "$@" \
    -o /dev/null 2>/dev/null || true
}

web_session() {
  local scheme="$1"
  local base paths total i path referer method

  if [[ "$scheme" == "https" ]]; then
    base="$HTTPS_BASE"
  else
    base="$HTTP_BASE"
  fi

  paths=(
    "/"
    "/index.html"
    "/favicon.ico"
    "/robots.txt"
    "/assets/app.css"
    "/assets/main.js"
    "/docs"
    "/status"
    "/login"
    "/does-not-exist"
  )

  total="$(rand_between "$WEB_MIN" "$WEB_MAX")"
  referer="$base/"
  log "WEB ${scheme^^}: session ${total} requetes vers $base"

  for ((i = 1; i <= total; i++)); do
    still_running || return 0

    path="${paths[$((RANDOM % ${#paths[@]}))]}"
    method="GET"
    (( RANDOM % 100 < 8 )) && method="HEAD"

    if [[ "$scheme" == "https" ]]; then
      curl_common -k -X "$method" -e "$referer" "$base$path"
    else
      curl_common -X "$method" -e "$referer" "$base$path"
    fi

    ACTION_COUNT=$((ACTION_COUNT + 1))
    referer="$base$path"

    # Chargement de 1-3 "ressources" juste apres une page, comme un navigateur.
    if (( RANDOM % 100 < 35 )); then
      if [[ "$scheme" == "https" ]]; then
        curl_common -k "$base/favicon.ico"
      else
        curl_common "$base/favicon.ico"
      fi
      short_pause
    fi

    sleep "$(rand_between "$WEB_SLEEP_MIN" "$WEB_SLEEP_MAX")"
  done
}

dns_session() {
  local domains types total i domain qtype
  domains=(
    "google.com"
    "github.com"
    "debian.org"
    "ubuntu.com"
    "kali.org"
    "python.org"
    "wikipedia.org"
    "mozilla.org"
    "cloudflare.com"
    "stackoverflow.com"
    "packages.debian.org"
    "security.ubuntu.com"
    "archive.ubuntu.com"
    "example.com"
  )
  types=("A" "AAAA" "A" "A" "MX" "NS")
  total="$(rand_between "$DNS_MIN" "$DNS_MAX")"
  log "DNS: session ${total} requetes via $DNS_SERVER"

  for ((i = 1; i <= total; i++)); do
    still_running || return 0
    domain="${domains[$((RANDOM % ${#domains[@]}))]}"
    qtype="${types[$((RANDOM % ${#types[@]}))]}"

    dig "@${DNS_SERVER}" "$domain" "$qtype" +time=2 +tries=1 +short >/dev/null 2>&1 || true
    ACTION_COUNT=$((ACTION_COUNT + 1))

    # Un navigateur refait souvent une resolution proche, mais pas en flood.
    if (( RANDOM % 100 < 25 )); then
      sleep "$(rand_between 1 3)"
      dig "@${DNS_SERVER}" "$domain" "AAAA" +time=2 +tries=1 +short >/dev/null 2>&1 || true
      ACTION_COUNT=$((ACTION_COUNT + 1))
    fi

    sleep "$(rand_between "$DNS_SLEEP_MIN" "$DNS_SLEEP_MAX")"
  done
}

ssh_session() {
  local commands session_len remote_script
  commands=(
    "hostname"
    "whoami"
    "pwd"
    "date"
    "uptime"
    "ls -lah ~ | head -12"
    "df -h | head -8"
    "free -h"
    "ip -brief addr | head"
    "ss -tuna | head -12"
    "ps aux | head -10"
    "journalctl -n 5 --no-pager 2>/dev/null || true"
  )

  session_len="$(rand_between "$SSH_MIN" "$SSH_MAX")"
  remote_script="echo '[ssh] session normale'; "
  for ((i = 1; i <= session_len; i++)); do
    remote_script+="${commands[$((RANDOM % ${#commands[@]}))]}; "
    remote_script+="sleep $(rand_between "$SSH_SLEEP_MIN" "$SSH_SLEEP_MAX"); "
  done
  remote_script+="echo '[ssh] fin';"

  log "SSH: session interactive courte (${session_len} commandes)"
  ssh \
    -tt \
    -p "$SSH_PORT" \
    -o StrictHostKeyChecking=accept-new \
    -o LogLevel=ERROR \
    -o ConnectTimeout=8 \
    "${SSH_USER}@${TARGET}" \
    "$remote_script" || warn "SSH non etabli (cle/mdp/service indisponible)"

  ACTION_COUNT=$((ACTION_COUNT + 1))
}

ssh_rare_failure() {
  [[ "$INCLUDE_SSH_FAILURES" == "1" ]] || return 0
  (( RANDOM % 100 < 12 )) || return 0

  log "SSH: echec rare simule (option INCLUDE_SSH_FAILURES=1)"
  ssh \
    -p "$SSH_PORT" \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    -o ConnectTimeout=4 \
    "user_${RANDOM}@${TARGET}" \
    "true" >/dev/null 2>&1 || true
  ACTION_COUNT=$((ACTION_COUNT + 1))
}

apt_like_session() {
  local urls total i url
  urls=(
    "${HTTP_BASE}/"
    "${HTTP_BASE}/index.html"
    "http://deb.debian.org/debian/dists/stable/Release"
    "http://security.debian.org/debian-security/dists/stable-security/Release"
    "http://archive.ubuntu.com/ubuntu/dists/jammy/Release"
  )
  total="$(rand_between "$APT_MIN" "$APT_MAX")"
  log "APT-like: ${total} petits telechargements"

  for ((i = 1; i <= total; i++)); do
    still_running || return 0
    url="${urls[$((RANDOM % ${#urls[@]}))]}"
    curl_common -r "0-$(rand_between 20000 120000)" "$url"
    ACTION_COUNT=$((ACTION_COUNT + 1))
    sleep "$(rand_between "$APT_SLEEP_MIN" "$APT_SLEEP_MAX")"
  done
}

mixed_natural_burst() {
  # Petite simultaneite legitime: page web + DNS autour du meme moment.
  log "MIX: petite simultaneite naturelle"
  dns_session &
  local dns_pid=$!
  sleep "$(rand_between 1 4)"
  if (( RANDOM % 2 == 0 )); then
    web_session "http"
  else
    web_session "https"
  fi
  wait "$dns_pid" 2>/dev/null || true
}

print_help() {
  printf '[INFO] cible=%s user=%s duree=%smin\n' "$TARGET" "$SSH_USER" "$DURATION_MIN"
}

main() {
  need_cmd curl
  need_cmd dig
  need_cmd ssh

  print_help
  sleep 2

  while still_running; do
    roll=$((RANDOM % 100))
    if (( roll < 28 )); then
      web_session "http"
    elif (( roll < 50 )); then
      web_session "https"
    elif (( roll < 72 )); then
      dns_session
    elif (( roll < 85 )); then
      ssh_session
      ssh_rare_failure
    elif (( roll < 94 )); then
      apt_like_session
    else
      mixed_natural_burst
    fi

    weighted_sleep
  done

  ok "termine - ${ACTION_COUNT} actions effectuees"
}

main "$@"
