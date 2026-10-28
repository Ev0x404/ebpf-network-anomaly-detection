#!/usr/bin/env python3

import json
import socket
import struct
import subprocess
from collections import defaultdict, deque
from datetime import datetime

# on surveille uniquement SSH, HTTP et HTTPS pour les features par service
SERVICE_PORTS = {
    "ssh": {22},
    "http": {80},
    "https": {443},
}

# liste des features dans l'ordre exact attendu par le modele sklearn
FEATURE_COLS = [
    # Fenetre 5s -> activite globale
    "w5_delta_connexions",
    "w5_nb_ports",
    "w5_delta_syn",
    "w5_delta_rst",
    "w5_syn_ratio",

    # Fenetre 5s -> activite service
    "w5_connexions_ssh",
    "w5_connexions_http",
    "w5_connexions_https",

    # Fenetre 5s -> activite DNS
    "w5_dns_pkt",
    "w5_dns_bytes",
    "w5_dns_long_lbl",

    # Fenetre 60s -> activite globale
    "w60_delta_connexions",
    "w60_nb_ports",
    "w60_delta_syn",
    "w60_delta_rst",
    "w60_syn_ratio",

    # Fenetre 60s -> activite service
    "w60_connexions_ssh",
    "w60_connexions_http",
    "w60_connexions_https",

    # Fenetre 60s -> activite DNS
    "w60_dns_pkt",
    "w60_dns_bytes",
    "w60_dns_long_lbl",
    "w60_dns_avg_size",
    "w60_dns_large_ratio",

    # Fenetre 300s -> activite globale
    "w300_delta_connexions",
    "w300_nb_ports",
    "w300_delta_rst",
    "w300_syn_ratio",

    # Fenetre 300s -> activite service
    "w300_connexions_ssh",
    "w300_connexions_http",
    "w300_connexions_https",

    # Fenetre 300s -> activite DNS
    "w300_dns_pkt",
    "w300_dns_bytes",
    "w300_dns_long_lbl",
    "w300_dns_avg_size",
    "w300_dns_large_ratio",
]

# 60 snapshots de 5s = 5 minutes d'historique max
HISTORY_MAXLEN = 60

# _prev stocke le dernier snapshot lu pour chaque IP (pour calculer les deltas)
# _history garde les 60 derniers snapshots par IP (fenetres glissantes)
_prev = {}
_history = defaultdict(lambda: deque(maxlen=HISTORY_MAXLEN))


# Lecture des maps 

def run_bpftool(map_name):
    # dump la map eBPF en JSON via bpftool, retourne [] si ca plante
    try:
        result = subprocess.run(
            ["sudo", "bpftool", "map", "dump", "name", map_name, "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        return json.loads(result.stdout)
    except Exception as e:
        print(f"[COLLECTOR] Erreur lecture map {map_name} : {e}")
        return []


def ip_from_bpf(raw):
    # bpftool peut retourner l'IP sous 3 formes differentes selon la version du kernel (ou bpftool), donc on gere les 3 cas
    try:
        if isinstance(raw, list):
            octets = [int(b, 16) if isinstance(b, str) else int(b) for b in raw]
            return socket.inet_ntoa(bytes(octets))
        if isinstance(raw, int):
            # stocke en little-endian dans le kernel
            return socket.inet_ntoa(struct.pack("<I", raw))
        if isinstance(raw, str):
            return socket.inet_ntoa(struct.pack("<I", int(raw, 16)))
    except Exception:
        return str(raw)


def parse_icmp_map(entries):
    # ip -> nombre de paquets ICMP recus
    out = {}
    for e in entries:
        try:
            fmt = e.get("formatted", {})
            out[ip_from_bpf(fmt["key"])] = int(fmt["value"])
        except Exception:
            continue
    return out


def parse_tcp_map(entries):
    # tcp_map est agregee par IP (pas par port), donc on ne sait pas
    # quels SYN/RST appartiennent a SSH ou HTTP, juste le total par IP
    out = {}
    for e in entries:
        try:
            fmt = e.get("formatted", {})
            ip = ip_from_bpf(fmt["key"])
            val = fmt["value"]
            if isinstance(val, dict):
                out[ip] = {k: int(val.get(k, 0)) for k in ("syn", "ack", "fin", "rst", "psh")}
            else:
                out[ip] = {"syn": 0, "ack": 0, "fin": 0, "rst": 0, "psh": 0}
        except Exception:
            continue
    return out


def parse_conn_map(entries):
    # conn_map est indexee par (src_ip, dst_port) et compte tous les paquets TCP
    out = defaultdict(lambda: {
        "ports": set(),
        "nb_connexions": 0,
        "by_port": defaultdict(int),
    })

    for e in entries:
        try:
            fmt = e.get("formatted", {})
            key = fmt.get("key", {})
            val = int(fmt.get("value", 0))

            ip = ip_from_bpf(key["src_ip"])
            port = int(key["dst_port"])

            out[ip]["ports"].add(port)
            out[ip]["nb_connexions"] += val
            out[ip]["by_port"][port] += val
        except Exception:
            continue

    return dict(out)


def parse_dns_map(entries):
    # lit dns_map : src_ip -> {pkt_count, bytes_total, label_long}
    # le format de la valeur peut varier selon le BPF compile donc on gere les deux cas
    out = {}
    for e in entries:
        try:
            fmt = e.get("formatted", {})
            ip = ip_from_bpf(fmt["key"])
            val = fmt["value"]

            if isinstance(val, dict):
                out[ip] = {
                    "pkt_count": int(val.get("pkt_count", 0)),
                    "bytes_total": int(val.get("bytes_total", 0)),
                    "label_long": int(val.get("label_long", 0)),
                }
            elif isinstance(val, list) and len(val) >= 3:
                out[ip] = {
                    "pkt_count": int(val[0]),
                    "bytes_total": int(val[1]),
                    "label_long": int(val[2]),
                }
            else:
                out[ip] = {"pkt_count": 0, "bytes_total": 0, "label_long": 0}
        except Exception:
            continue
    return out


def parse_pid_map(entries):
    # On récupère les processus actifs et leur nombre de connexions
    out = defaultdict(int)
    for e in entries:
        try:
            fmt = e.get("formatted", {})
            val = fmt.get("value", {})
            comm = str(val.get("comm", "unknown")).strip("\\x00")
            count = int(val.get("count", 0))
            out[comm] += count
        except Exception:
            continue
    return dict(out)


# Helpers services
def delta_conn_for_service(curr_by_port, prev_by_port, ports):
    # calcule combien de nouveaux paquets sont arrives sur les ports du service
    total = 0
    for port in ports:
        total += max(0, curr_by_port.get(port, 0) - prev_by_port.get(port, 0))
    return total


# Agregation des fenetres
def aggregate_window(ip_deque, n_snapshots):
    # additionne les n derniers snapshots pour obtenir les metriques sur la fenetre
    snapshots = list(ip_deque)[-n_snapshots:]
    if not snapshots:
        return {
            "delta_conx": 0,
            "nb_ports": 0,
            "delta_syn": 0,
            "delta_ack": 0,
            "delta_fin": 0,
            "delta_rst": 0,
            "syn_ratio": 0.0,
            "connexions_ssh": 0,
            "connexions_http": 0,
            "connexions_https": 0,
            "dns_pkt": 0,
            "dns_bytes": 0,
            "dns_long_lbl": 0,
        }

    all_ports = set()
    delta_conx = 0
    delta_syn = 0
    delta_ack = 0
    delta_fin = 0
    delta_rst = 0
    connexions_ssh = 0
    connexions_http = 0
    connexions_https = 0
    dns_pkt = 0
    dns_bytes = 0
    dns_long_lbl = 0

    for s in snapshots:
        all_ports |= s["new_ports"]
        delta_conx += s["delta_conx"]
        delta_syn += s["delta_syn"]
        delta_ack += s["delta_ack"]
        delta_fin += s["delta_fin"]
        delta_rst += s["delta_rst"]
        connexions_ssh += s["delta_conx_ssh"]
        connexions_http += s["delta_conx_http"]
        connexions_https += s["delta_conx_https"]
        dns_pkt += s["delta_dns_pkt"]
        dns_bytes += s["delta_dns_bytes"]
        dns_long_lbl += s["delta_dns_long_lbl"]

    # syn_ratio = proportion de SYN parmi tous les flags TCP
    # si proche de 1.0 = trafic pur SYN (suspect), bas = connexions normales
    total = delta_syn + delta_ack + delta_fin + delta_rst
    syn_ratio = round(delta_syn / total, 3) if total > 0 else 0.0

    return {
        "delta_conx": delta_conx,
        "nb_ports": len(all_ports),
        "delta_syn": delta_syn,
        "delta_ack": delta_ack,
        "delta_fin": delta_fin,
        "delta_rst": delta_rst,
        "syn_ratio": syn_ratio,
        "connexions_ssh": connexions_ssh,
        "connexions_http": connexions_http,
        "connexions_https": connexions_https,
        "dns_pkt": dns_pkt,
        "dns_bytes": dns_bytes,
        "dns_long_lbl": dns_long_lbl,
    }


def collect_features():
    # lit toutes les maps eBPF et retourne une liste de features par IP observee
    global _prev

    # on lit toutes les maps en une fois pour avoir un snapshot coherent
    icmp_data = parse_icmp_map(run_bpftool("icmp_map"))
    tcp_data = parse_tcp_map(run_bpftool("tcp_map"))
    conn_data = parse_conn_map(run_bpftool("conn_map"))
    dns_data = parse_dns_map(run_bpftool("dns_map"))
    pid_data = parse_pid_map(run_bpftool("pid_map"))

    # on initialise juste _prev avec les valeurs actuelles
    # pour que le prochain cycle puisse calculer des deltas corrects
    if not _prev:
        for ip in set(icmp_data) | set(tcp_data) | set(conn_data) | set(dns_data):
            tcp = tcp_data.get(ip, {"syn": 0, "ack": 0, "fin": 0, "rst": 0, "psh": 0})
            conn = conn_data.get(ip, {"ports": set(), "nb_connexions": 0, "by_port": defaultdict(int)})
            dns = dns_data.get(ip, {"pkt_count": 0, "bytes_total": 0, "label_long": 0})
            _prev[ip] = {
                "nb_connexions": conn["nb_connexions"],
                "syn": tcp["syn"],
                "ack": tcp["ack"],
                "fin": tcp["fin"],
                "rst": tcp["rst"],
                "ports": set(conn["ports"]),
                "by_port": dict(conn["by_port"]),
                "dns_pkt": dns["pkt_count"],
                "dns_bytes": dns["bytes_total"],
                "dns_long": dns["label_long"],
            }
        return []

    all_ips = set(icmp_data) | set(tcp_data) | set(conn_data) | set(dns_data)
    ts = datetime.now().isoformat(timespec="seconds")
    current = {}
    features = []

    for ip in all_ips:
        tcp = tcp_data.get(ip, {"syn": 0, "ack": 0, "fin": 0, "rst": 0, "psh": 0})
        conn = conn_data.get(ip, {"ports": set(), "nb_connexions": 0, "by_port": defaultdict(int)})
        dns = dns_data.get(ip, {"pkt_count": 0, "bytes_total": 0, "label_long": 0})
        icmp = icmp_data.get(ip, 0)

        # si c'est une nouvelle IP (pas dans _prev), on initialise avec les valeurs
        # actuelles pour que le delta de ce cycle soit 0 (evite les faux positifs)
        prev = _prev.get(ip, {
            "nb_connexions": conn["nb_connexions"],
            "syn": tcp["syn"],
            "ack": tcp["ack"],
            "fin": tcp["fin"],
            "rst": tcp["rst"],
            "ports": set(conn["ports"]),
            "by_port": dict(conn["by_port"]),
            "dns_pkt": dns["pkt_count"],
            "dns_bytes": dns["bytes_total"],
            "dns_long": dns["label_long"],
        })

        # Deltas globaux TCP
        delta_conx = max(0, conn["nb_connexions"] - prev["nb_connexions"])
        delta_syn = max(0, tcp["syn"] - prev["syn"])
        delta_ack = max(0, tcp["ack"] - prev["ack"])
        delta_fin = max(0, tcp["fin"] - prev["fin"])
        delta_rst = max(0, tcp["rst"] - prev["rst"])

        # Deltas par service
        delta_conx_ssh = delta_conn_for_service(conn["by_port"], prev["by_port"], SERVICE_PORTS["ssh"])
        delta_conx_http = delta_conn_for_service(conn["by_port"], prev["by_port"], SERVICE_PORTS["http"])
        delta_conx_https = delta_conn_for_service(conn["by_port"], prev["by_port"], SERVICE_PORTS["https"])

        # Deltas DNS
        delta_dns_pkt = max(0, dns["pkt_count"] - prev["dns_pkt"])
        delta_dns_bytes = max(0, dns["bytes_total"] - prev["dns_bytes"])
        delta_dns_long = max(0, dns["label_long"] - prev["dns_long"])

        new_ports = conn["ports"] - prev["ports"]

        # sauvegarde l'etat actuel pour le prochain cycle
        current[ip] = {
            "nb_connexions": conn["nb_connexions"],
            "syn": tcp["syn"],
            "ack": tcp["ack"],
            "fin": tcp["fin"],
            "rst": tcp["rst"],
            "ports": set(conn["ports"]),
            "by_port": dict(conn["by_port"]),
            "dns_pkt": dns["pkt_count"],
            "dns_bytes": dns["bytes_total"],
            "dns_long": dns["label_long"],
        }

        # ajout du snapshot dans l'historique de l'IP
        _history[ip].append({
            "new_ports": new_ports,
            "delta_conx": delta_conx,
            "delta_syn": delta_syn,
            "delta_ack": delta_ack,
            "delta_fin": delta_fin,
            "delta_rst": delta_rst,
            "delta_conx_ssh": delta_conx_ssh,
            "delta_conx_http": delta_conx_http,
            "delta_conx_https": delta_conx_https,
            "delta_dns_pkt": delta_dns_pkt,
            "delta_dns_bytes": delta_dns_bytes,
            "delta_dns_long_lbl": delta_dns_long,
        })

        # agregation sur les 3 fenetres de temps
        w5 = aggregate_window(_history[ip], 1)   # 1 snapshot  = 5s
        w60 = aggregate_window(_history[ip], 12)  # 12 snapshots = 60s
        w300 = aggregate_window(_history[ip], 60) # 60 snapshots = 300s

        # Features derivees DNS : taille moyenne et ratio de gros labels
        w60_dns_avg_size = round(w60["dns_bytes"] / w60["dns_pkt"], 3) if w60["dns_pkt"] > 0 else 0.0
        w300_dns_avg_size = round(w300["dns_bytes"] / w300["dns_pkt"], 3) if w300["dns_pkt"] > 0 else 0.0

        w60_dns_large_ratio = round(w60["dns_long_lbl"] / w60["dns_pkt"], 3) if w60["dns_pkt"] > 0 else 0.0
        w300_dns_large_ratio = round(w300["dns_long_lbl"] / w300["dns_pkt"], 3) if w300["dns_pkt"] > 0 else 0.0

        features.append({
            "src_ip": ip,
            "timestamp": ts,
            "icmp_count": icmp,
            "pid_activity": pid_data,
            # total_distinct_ports = nb de ports uniques dans conn_map (depuis le debut)
            # utile pour detecter les rescans meme quand new_ports = 0
            "total_distinct_ports": len(conn["ports"]),

            # Fenetre 5s -> global
            "w5_delta_connexions": w5["delta_conx"],
            "w5_nb_ports": w5["nb_ports"],
            "w5_delta_syn": w5["delta_syn"],
            "w5_delta_rst": w5["delta_rst"],
            "w5_syn_ratio": w5["syn_ratio"],

            # Fenetre 5s -> service
            "w5_connexions_ssh": w5["connexions_ssh"],
            "w5_connexions_http": w5["connexions_http"],
            "w5_connexions_https": w5["connexions_https"],

            # Fenetre 5s -> DNS
            "w5_dns_pkt": w5["dns_pkt"],
            "w5_dns_bytes": w5["dns_bytes"],
            "w5_dns_long_lbl": w5["dns_long_lbl"],

            # Fenetre 60s -> global
            "w60_delta_connexions": w60["delta_conx"],
            "w60_nb_ports": w60["nb_ports"],
            "w60_delta_syn": w60["delta_syn"],
            "w60_delta_rst": w60["delta_rst"],
            "w60_syn_ratio": w60["syn_ratio"],

            # Fenetre 60s -> service
            "w60_connexions_ssh": w60["connexions_ssh"],
            "w60_connexions_http": w60["connexions_http"],
            "w60_connexions_https": w60["connexions_https"],

            # Fenetre 60s -> DNS
            "w60_dns_pkt": w60["dns_pkt"],
            "w60_dns_bytes": w60["dns_bytes"],
            "w60_dns_long_lbl": w60["dns_long_lbl"],
            "w60_dns_avg_size": w60_dns_avg_size,
            "w60_dns_large_ratio": w60_dns_large_ratio,

            # Fenetre 300s - global
            "w300_delta_connexions": w300["delta_conx"],
            "w300_nb_ports": w300["nb_ports"],
            "w300_delta_rst": w300["delta_rst"],
            "w300_syn_ratio": w300["syn_ratio"],

            # Fenetre 300s -> service
            "w300_connexions_ssh": w300["connexions_ssh"],
            "w300_connexions_http": w300["connexions_http"],
            "w300_connexions_https": w300["connexions_https"],

            # Fenetre 300s -> DNS
            "w300_dns_pkt": w300["dns_pkt"],
            "w300_dns_bytes": w300["dns_bytes"],
            "w300_dns_long_lbl": w300["dns_long_lbl"],
            "w300_dns_avg_size": w300_dns_avg_size,
            "w300_dns_large_ratio": w300_dns_large_ratio,
        })

    _prev = current
    return features


def reset_state():
    # On remet tout à zero (appeler au démarrage ou apres un reset des maps XDP)
    global _prev, _history
    _prev = {}
    _history = defaultdict(lambda: deque(maxlen=HISTORY_MAXLEN))


def reset_ip_state(ip):
    # efface l'historique d'une IP specifique apres un ban
    # sans ca les anciennes metriques d'attaque contaminent les cycles suivants
    _prev.pop(ip, None)
    _history.pop(ip, None)
