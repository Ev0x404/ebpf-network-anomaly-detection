#!/bin/bash

DURATION=${1:-600}
END=$((SECONDS + DURATION))

HTTP_SITES=(
    "http://example.com"
    "http://neverssl.com"
    "http://httpforever.com"
    "http://detectportal.firefox.com/success.txt"
    "http://www.msftconnecttest.com/connecttest.txt"
    "http://connectivitycheck.gstatic.com/generate_204"
    "http://plain-text-page.com"
    "http://icanhazip.com"
)

HTTPS_SITES=(
    "https://google.com"
    "https://ubuntu.com"
    "https://debian.org"
    "https://github.com"
    "https://cloudflare.com"
    "https://wikipedia.org"
    "https://python.org"
    "https://curl.se"
)

DNS_DOMAINS=(
    "ubuntu.com" "debian.org" "github.com" "google.com"
    "cloudflare.com" "wikipedia.org" "mozilla.org" "python.org"
    "kernel.org" "lxc.org" "docker.com" "openssl.org"
)

DNS_SERVERS=("8.8.8.8" "1.1.1.1" "8.8.4.4" "9.9.9.9")
PING_TARGETS=("8.8.8.8" "1.1.1.1" "8.8.4.4" "9.9.9.9")

DL_URLS=(
    "http://archive.ubuntu.com/ubuntu/dists/jammy/Release"
    "http://deb.debian.org/debian/dists/stable/Release"
    "http://ftp.fr.debian.org/debian/dists/bookworm/Release"
    "http://security.ubuntu.com/ubuntu/dists/jammy-security/Release"
)

echo "[TRAFFIC] Démarrage - durée : ${DURATION}s"
echo "[TRAFFIC] Objectif : w5_nb_ports p95 > 0"
echo ""

action_count=0

while [ $SECONDS -lt $END ]; do
    action_count=$((action_count + 1))
    remaining=$((END - SECONDS))

    # Tirage : 0-9
    action=$((RANDOM % 10))

    case $action in

        0|1)
            # 20% - requête HTTP simple
            site=${HTTP_SITES[$((RANDOM % ${#HTTP_SITES[@]}))]}
            curl -s --max-time 3 "$site" -o /dev/null 2>/dev/null
            printf "[%3ds] HTTP  : %s\n" $remaining "$site"
            ;;

        2|3)
            # 20% - requête HTTPS
            site=${HTTPS_SITES[$((RANDOM % ${#HTTPS_SITES[@]}))]}
            curl -s --max-time 4 "$site" -o /dev/null 2>/dev/null
            printf "[%3ds] HTTPS : %s\n" $remaining "$site"
            ;;

        4)
            # 10% - résolution DNS
            domain=${DNS_DOMAINS[$((RANDOM % ${#DNS_DOMAINS[@]}))]}
            server=${DNS_SERVERS[$((RANDOM % ${#DNS_SERVERS[@]}))]}
            nslookup "$domain" "$server" > /dev/null 2>/dev/null
            printf "[%3ds] DNS   : %s\n" $remaining "$domain"
            ;;

        5)
            # 10% - ping ICMP
            target=${PING_TARGETS[$((RANDOM % ${#PING_TARGETS[@]}))]}
            ping -c 2 -W 1 "$target" > /dev/null 2>/dev/null
            printf "[%3ds] PING  : %s\n" $remaining "$target"
            ;;

        6|7|8)
            # 30% - burst mixte parallèle (HTTP + HTTPS + DNS simultanés)
            # Cible directe sur w5_nb_ports : plusieurs destinations
            # simultanées depuis la VM dans la même fenêtre de 5s.
            # Effet sur new_ports : dépend de l'historique de l'IP source,
            # mais augmente la probabilité d'avoir des ports nouveaux dans
            # la fenêtre courte.
            printf "[%3ds] BURST : HTTP + HTTPS + DNS + PING simultanés\n" $remaining
            curl -s --max-time 3 \
                "${HTTP_SITES[$((RANDOM % ${#HTTP_SITES[@]}))]}" \
                -o /dev/null 2>/dev/null &
            curl -s --max-time 4 \
                "${HTTPS_SITES[$((RANDOM % ${#HTTPS_SITES[@]}))]}" \
                -o /dev/null 2>/dev/null &
            nslookup \
                "${DNS_DOMAINS[$((RANDOM % ${#DNS_DOMAINS[@]}))]}" \
                "${DNS_SERVERS[$((RANDOM % ${#DNS_SERVERS[@]}))]}" \
                > /dev/null 2>/dev/null &
            ping -c 1 -W 1 \
                "${PING_TARGETS[$((RANDOM % ${#PING_TARGETS[@]}))]}" \
                > /dev/null 2>/dev/null &
            wait
            ;;

        9)
            # 10% - téléchargement léger
            url=${DL_URLS[$((RANDOM % ${#DL_URLS[@]}))]}
            printf "[%3ds] DL    : %s\n" $remaining "$url"
            curl -s --max-time 5 "$url" -o /dev/null 2>/dev/null
            ;;

    esac

    # Sleep court : 0 ou 1 seconde - plusieurs actions par fenêtre de 5s
    sleep $((RANDOM % 2))

done

echo ""
echo "[TRAFFIC] Terminé - ${action_count} actions effectuées"
