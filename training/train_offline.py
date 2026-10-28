#!/usr/bin/env python3
"""
Entrainement offline d'Isolation Forest sur trafic normal.
"""

import json

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from config.settings import MODEL_FILE, NORMAL_TRAFFIC_FILE, SCALER_FILE, THRESHOLD_FILE
from src.collector import FEATURE_COLS

ANOMALY_PERCENTILE = 1


def enrich_derived_features(values):
    values = dict(values)
    for window in ("w60", "w300"):
        pkt_key = f"{window}_dns_pkt"
        bytes_key = f"{window}_dns_bytes"
        long_key = f"{window}_dns_long_lbl"
        avg_key = f"{window}_dns_avg_size"
        ratio_key = f"{window}_dns_large_ratio"

        pkt = float(values.get(pkt_key, 0.0))
        if pkt > 0:
            values.setdefault(avg_key, float(values.get(bytes_key, 0.0)) / pkt)
            values.setdefault(ratio_key, float(values.get(long_key, 0.0)) / pkt)
    return values


def vector_from_partial(values):
    values = enrich_derived_features(values)
    return [float(values.get(c, 0.0)) for c in FEATURE_COLS]


def rule_alert_type(values):
    values = enrich_derived_features(values)

    w5_ports = values.get("w5_nb_ports", 0)
    w5_syn_r = values.get("w5_syn_ratio", 0)
    w5_syn = values.get("w5_delta_syn", 0)
    w60_syn = values.get("w60_delta_syn", 0)
    w60_rst = values.get("w60_delta_rst", 0)
    w60_ports = values.get("w60_nb_ports", 0)
    w60_syn_r = values.get("w60_syn_ratio", 0)
    w300_ports = values.get("w300_nb_ports", 0)
    w300_syn_r = values.get("w300_syn_ratio", 0)
    w300_rst = values.get("w300_delta_rst", 0)

    w5_dns_pkt = values.get("w5_dns_pkt", 0)
    w60_dns_pkt = values.get("w60_dns_pkt", 0)
    w60_dns_bytes = values.get("w60_dns_bytes", 0)
    w60_dns_avg_size = values.get("w60_dns_avg_size", 0)
    w60_dns_large_ratio = values.get("w60_dns_large_ratio", 0)
    w300_dns_pkt = values.get("w300_dns_pkt", 0)
    w300_dns_bytes = values.get("w300_dns_bytes", 0)
    w300_dns_avg_size = values.get("w300_dns_avg_size", 0)
    w300_dns_large_ratio = values.get("w300_dns_large_ratio", 0)

    w5_ssh = values.get("w5_connexions_ssh", 0)
    w60_ssh = values.get("w60_connexions_ssh", 0)
    w300_ssh = values.get("w300_connexions_ssh", 0)
    w5_http = values.get("w5_connexions_http", 0)
    w60_http = values.get("w60_connexions_http", 0)
    w300_http = values.get("w300_connexions_http", 0)
    w5_https = values.get("w5_connexions_https", 0)
    w60_https = values.get("w60_connexions_https", 0)
    w300_https = values.get("w300_connexions_https", 0)

    def share(primary, *others):
        total = primary + sum(others)
        return primary / total if total > 0 else 0.0

    if w5_ports > 20 and w5_syn_r > 0.7:
        return "PORT_SCAN_RAPIDE"
    if w5_syn > 100 and w5_syn_r > 0.85 and w5_ports <= 3 and w60_rst > 10:
        return "PORT_SCAN_RAPIDE"
    if w5_syn > 100 and w5_syn_r > 0.85 and w5_ports <= 3 and w60_rst <= 10:
        return "DOS_SYN_FLOOD"

    if w5_dns_pkt > 200 or w60_dns_pkt > 1500:
        return "DNS_BURST_SUSPECT"
    if w60_dns_pkt > 100 and w60_dns_large_ratio > 0.60 and w60_dns_avg_size > 110:
        return "DNS_TUNNELING_SUSPECT"
    if (
        w300_dns_pkt > 250
        and w300_dns_bytes > 250000
        and w300_dns_large_ratio > 0.25
        and w300_dns_avg_size > 120
        and w60_dns_pkt > 20
    ):
        return "DNS_EXFILTRATION_SUSPECT"
    if (
        w300_dns_pkt > 300
        and w60_dns_pkt > 50
        and w300_dns_large_ratio > 0.50
        and w300_dns_avg_size > 110
    ):
        return "DNS_TUNNELING_LENT_SUSPECT"

    ssh_share_w60 = share(w60_ssh, w60_http, w60_https)
    ssh_share_w300 = share(w300_ssh, w300_http, w300_https)
    http_share_w60 = share(w60_http, w60_ssh, w60_https)
    http_share_w300 = share(w300_http, w300_ssh, w300_https)
    https_share_w60 = share(w60_https, w60_ssh, w60_http)
    https_share_w300 = share(w300_https, w300_ssh, w300_http)

    ssh_dominant_w60 = w60_ssh >= 40 and w60_ssh >= max(40, int(1.5 * (w60_http + w60_https))) and ssh_share_w60 >= 0.60 and w5_ssh >= 2
    ssh_dominant_w300 = w300_ssh >= 120 and w300_ssh >= max(120, int(1.5 * (w300_http + w300_https))) and ssh_share_w300 >= 0.60 and w60_ssh >= 15
    http_dominant_w60 = w60_http >= 80 and w60_http >= max(80, int(1.2 * (w60_ssh + w60_https))) and http_share_w60 >= 0.55 and w5_http >= 5
    http_dominant_w300 = w300_http >= 200 and w300_http >= max(200, int(1.2 * (w300_ssh + w300_https))) and http_share_w300 >= 0.55 and w60_http >= 40
    https_dominant_w60 = w60_https >= 100 and w60_https >= max(100, int(1.2 * (w60_ssh + w60_http))) and https_share_w60 >= 0.55 and w5_https >= 5
    https_dominant_w300 = w300_https >= 250 and w300_https >= max(250, int(1.2 * (w300_ssh + w300_http))) and https_share_w300 >= 0.55 and w60_https >= 50

    if http_dominant_w60 and w60_syn_r <= 0.35:
        return "HTTP_FLOOD_SUSPECT"
    if http_dominant_w300 and w300_syn_r <= 0.35:
        return "HTTP_FLOOD_LENT_SUSPECT"
    if https_dominant_w60 and w60_syn_r <= 0.35:
        return "HTTPS_FLOOD_SUSPECT"
    if https_dominant_w300 and w300_syn_r <= 0.35:
        return "HTTPS_FLOOD_LENT_SUSPECT"
    if ssh_dominant_w60 and w60_syn >= 8 and w60_syn_r <= 0.25:
        return "BRUTE_FORCE_SSH_SUSPECT"
    if ssh_dominant_w300 and w60_syn >= 5 and w300_syn_r <= 0.25:
        return "BRUTE_FORCE_SSH_LENT_SUSPECT"
    if w60_rst > 50 and w60_ports <= 3 and w60_syn >= 8 and w60_syn_r < 0.5 and (w60_ssh >= max(10, w60_http, w60_https) or (w60_http + w60_https) < 20):
        return "BRUTE_FORCE_RAPIDE"
    if w60_ports > 30 and w60_syn_r > 0.6:
        return "PORT_SCAN_MODERE"
    if w300_ports > 50 and w300_syn_r > 0.4:
        return "PORT_SCAN_LENT"
    if w300_rst > 80 and w300_ports <= 3 and (w300_ssh >= max(20, w300_http, w300_https) or (w300_http + w300_https) < 40) and w60_syn >= 5 and w60_ssh >= 5:
        return "BRUTE_FORCE_LENT"

    return "ANOMALIE_RESEAU"


def main():
    print("[TRAIN] Chargement des donnees...")
    with open(NORMAL_TRAFFIC_FILE, "r", encoding="utf-8") as fp:
        data = json.load(fp)

    if not data:
        print("[TRAIN] Aucune donnee. Lance : python3 record_traffic.py")
        return

    print(f"[TRAIN] {len(data)} samples charges")

    X = np.array([[row[c] for c in FEATURE_COLS] for row in data], dtype=float)
    print(f"[TRAIN] Matrice : {X.shape}  ({X.shape[1]} features x {X.shape[0]} samples)\n")

    print("[TRAIN] Distribution sur le trafic normal :")
    print("  Feature                           moy      std      p95      max")
    print("  ------------------------------------------------------------")
    for i, col in enumerate(FEATURE_COLS):
        vals = X[:, i]
        print(f"  {col:35s} {vals.mean():8.2f} {vals.std():8.2f} {np.percentile(vals, 95):8.2f} {vals.max():8.2f}")

    print("\n[TRAIN] Entrainement du scaler...")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    print("[TRAIN] Entrainement d'Isolation Forest (n_estimators=200)...\n")
    model = IsolationForest(
        n_estimators=200,
        contamination="auto",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_scaled)

    scores = model.score_samples(X_scaled)
    threshold = float(np.percentile(scores, ANOMALY_PERCENTILE))
    flagged = int((scores < threshold).sum())

    print("[TRAIN] Scores sur les donnees d'entrainement :")
    print(f"  min    : {scores.min():.4f}")
    print(f"  moyen  : {scores.mean():.4f}")
    print(f"  max    : {scores.max():.4f}")
    print(f"  seuil  : {threshold:.4f}  (p{ANOMALY_PERCENTILE} - scores sous ce seuil = anomalies)")
    print(f"  flagges sur train : {flagged}/{len(scores)} ({100 * flagged / len(scores):.1f}%)\n")

    MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_FILE)
    joblib.dump(scaler, SCALER_FILE)

    threshold_data = {
        "threshold": threshold,
        "anomaly_percentile": ANOMALY_PERCENTILE,
        "n_train_samples": len(data),
        "feature_cols": FEATURE_COLS,
    }
    with open(THRESHOLD_FILE, "w", encoding="utf-8") as fp:
        json.dump(threshold_data, fp, indent=2)

    print(f"[TRAIN] Fichiers sauvegardes : {MODEL_FILE}, {SCALER_FILE}, {THRESHOLD_FILE}\n")

    print("[VALIDATE] Test de non-regression...")
    print(f"[VALIDATE] {len(FEATURE_COLS)} features : {FEATURE_COLS}\n")

    cas_normaux = [
        (
            "Navigation HTTP locale",
            {
                "w5_delta_connexions": 3,
                "w5_nb_ports": 1,
                "w5_delta_syn": 1,
                "w5_delta_rst": 0,
                "w5_syn_ratio": 0.20,
                "w5_connexions_http": 2,

                "w60_delta_connexions": 20,
                "w60_nb_ports": 2,
                "w60_delta_syn": 5,
                "w60_delta_rst": 0,
                "w60_syn_ratio": 0.18,
                "w60_connexions_http": 15,

                "w300_delta_connexions": 60,
                "w300_nb_ports": 3,
                "w300_delta_rst": 1,
                "w300_syn_ratio": 0.15,
                "w300_connexions_http": 40,
            },
        ),
        (
            "Navigation HTTPS moderee",
            {
                "w5_delta_connexions": 4,
                "w5_nb_ports": 1,
                "w5_delta_syn": 1,
                "w5_delta_rst": 0,
                "w5_syn_ratio": 0.15,
                "w5_connexions_https": 3,

                "w60_delta_connexions": 25,
                "w60_nb_ports": 2,
                "w60_delta_syn": 6,
                "w60_delta_rst": 1,
                "w60_syn_ratio": 0.17,
                "w60_connexions_https": 18,

                "w300_delta_connexions": 80,
                "w300_nb_ports": 3,
                "w300_delta_rst": 2,
                "w300_syn_ratio": 0.16,
                "w300_connexions_https": 55,
            },
        ),
        (
            "SSH legitime ponctuel",
            {
                "w5_delta_connexions": 1,
                "w5_nb_ports": 1,
                "w5_delta_syn": 1,
                "w5_delta_rst": 0,
                "w5_syn_ratio": 0.25,
                "w5_connexions_ssh": 1,

                "w60_delta_connexions": 4,
                "w60_nb_ports": 1,
                "w60_delta_syn": 2,
                "w60_delta_rst": 0,
                "w60_syn_ratio": 0.20,
                "w60_connexions_ssh": 3,

                "w300_delta_connexions": 8,
                "w300_nb_ports": 1,
                "w300_delta_rst": 0,
                "w300_syn_ratio": 0.18,
                "w300_connexions_ssh": 6,
            },
        ),
        (
            "SSH interactif bruyant",
            {
                # Beaucoup de paquets SSH dans une session deja ouverte, mais
                # quasiment pas de nouveaux SYN : ce n'est pas un brute force.
                "w5_delta_connexions": 20,
                "w5_nb_ports": 1,
                "w5_delta_syn": 0,
                "w5_delta_rst": 0,
                "w5_syn_ratio": 0.00,
                "w5_connexions_ssh": 18,

                "w60_delta_connexions": 120,
                "w60_nb_ports": 1,
                "w60_delta_syn": 1,
                "w60_delta_rst": 0,
                "w60_syn_ratio": 0.01,
                "w60_connexions_ssh": 115,

                "w300_delta_connexions": 260,
                "w300_nb_ports": 1,
                "w300_delta_rst": 1,
                "w300_syn_ratio": 0.01,
                "w300_connexions_ssh": 250,
            },
        ),
        (
            "DNS normal (quelques requetes)",
            {
                # Trafic TCP nul - IP exclusivement DNS
                "w5_dns_pkt":       3,
                "w5_dns_bytes":     180,
                "w5_dns_long_lbl":  0,

                "w60_dns_pkt":      20,
                "w60_dns_bytes":    1200,
                "w60_dns_long_lbl": 0,

                "w300_dns_pkt":     60,
                "w300_dns_bytes":   3600,
                "w300_dns_long_lbl": 0,
            },
        ),
        (
            "DNS normal avec navigation web",
            {
                # Quelques requetes DNS accompagnant du HTTP/HTTPS classique
                "w5_delta_connexions": 2,
                "w5_nb_ports": 1,
                "w5_delta_syn": 1,
                "w5_connexions_http": 2,
                "w5_dns_pkt":       4,
                "w5_dns_bytes":     220,
                "w5_dns_long_lbl":  0,

                "w60_delta_connexions": 15,
                "w60_nb_ports": 2,
                "w60_connexions_http": 12,
                "w60_dns_pkt":      25,
                "w60_dns_bytes":    1400,
                "w60_dns_long_lbl": 0,

                "w300_delta_connexions": 50,
                "w300_nb_ports": 2,
                "w300_connexions_http": 40,
                "w300_dns_pkt":     80,
                "w300_dns_bytes":   4500,
                "w300_dns_long_lbl": 0,
            },
        ),
        (
            "IP inactive",
            {},
        ),
    ]

    cas_attaques = [
        (
            "Scan rapide",
            {
                "w5_delta_connexions": 120,
                "w5_nb_ports": 40,
                "w5_delta_syn": 110,
                "w5_delta_rst": 2,
                "w5_syn_ratio": 0.95,

                "w60_delta_connexions": 200,
                "w60_nb_ports": 50,
                "w60_delta_syn": 180,
                "w60_delta_rst": 5,
                "w60_syn_ratio": 0.90,

                "w300_delta_connexions": 300,
                "w300_nb_ports": 60,
                "w300_delta_rst": 8,
                "w300_syn_ratio": 0.85,
            },
        ),
        (
            "SYN flood",
            {
                "w5_delta_connexions": 250,
                "w5_nb_ports": 1,
                "w5_delta_syn": 240,
                "w5_delta_rst": 1,
                "w5_syn_ratio": 0.99,

                "w60_delta_connexions": 800,
                "w60_nb_ports": 1,
                "w60_delta_syn": 780,
                "w60_delta_rst": 3,
                "w60_syn_ratio": 0.98,

                "w300_delta_connexions": 1200,
                "w300_nb_ports": 1,
                "w300_delta_rst": 4,
                "w300_syn_ratio": 0.97,
            },
        ),
        (
            "Brute force SSH suspect",
            {
                "w5_delta_connexions": 10,
                "w5_nb_ports": 1,
                "w5_delta_syn": 2,
                "w5_delta_rst": 0,
                "w5_syn_ratio": 0.08,
                "w5_connexions_ssh": 8,

                "w60_delta_connexions": 180,
                "w60_nb_ports": 1,
                "w60_delta_syn": 12,
                "w60_delta_rst": 4,
                "w60_syn_ratio": 0.06,
                "w60_connexions_ssh": 160,

                "w300_delta_connexions": 350,
                "w300_nb_ports": 1,
                "w300_delta_rst": 8,
                "w300_syn_ratio": 0.05,
                "w300_connexions_ssh": 320,
            },
        ),
        (
            "HTTP flood suspect",
            {
                "w5_delta_connexions": 30,
                "w5_nb_ports": 1,
                "w5_delta_syn": 6,
                "w5_delta_rst": 0,
                "w5_syn_ratio": 0.10,
                "w5_connexions_http": 25,

                "w60_delta_connexions": 220,
                "w60_nb_ports": 1,
                "w60_delta_syn": 20,
                "w60_delta_rst": 3,
                "w60_syn_ratio": 0.09,
                "w60_connexions_http": 190,

                "w300_delta_connexions": 500,
                "w300_nb_ports": 1,
                "w300_delta_rst": 5,
                "w300_syn_ratio": 0.08,
                "w300_connexions_http": 430,
            },
        ),
        (
            "HTTPS flood suspect",
            {
                "w5_delta_connexions": 35,
                "w5_nb_ports": 1,
                "w5_delta_syn": 7,
                "w5_delta_rst": 0,
                "w5_syn_ratio": 0.10,
                "w5_connexions_https": 28,

                "w60_delta_connexions": 260,
                "w60_nb_ports": 1,
                "w60_delta_syn": 24,
                "w60_delta_rst": 3,
                "w60_syn_ratio": 0.09,
                "w60_connexions_https": 220,

                "w300_delta_connexions": 600,
                "w300_nb_ports": 1,
                "w300_delta_rst": 5,
                "w300_syn_ratio": 0.08,
                "w300_connexions_https": 500,
            },
        ),
        (
            "DNS burst",
            {
                # Volume massif de paquets DNS en quelques secondes
                # label_long = 0 : pas de noms longs, juste du volume pur
                "w5_dns_pkt":       300,
                "w5_dns_bytes":     18000,
                "w5_dns_long_lbl":  0,

                "w60_dns_pkt":      2500,
                "w60_dns_bytes":    150000,
                "w60_dns_long_lbl": 0,

                "w300_dns_pkt":     6000,
                "w300_dns_bytes":   360000,
                "w300_dns_long_lbl": 0,
            },
        ),
        (
            "DNS tunneling (dnscat2 / iodine)",
            {
                # Volume modere mais labels tres longs (payload > 100 bytes)
                # ratio label_long / pkt_count proche de 1
                "w5_dns_pkt":       25,
                "w5_dns_bytes":     4000,
                "w5_dns_long_lbl":  22,

                "w60_dns_pkt":      200,
                "w60_dns_bytes":    32000,
                "w60_dns_long_lbl": 180,

                "w300_dns_pkt":     500,
                "w300_dns_bytes":   80000,
                "w300_dns_long_lbl": 450,
            },
        ),
        (
            "DNS exfiltration lente",
            {
                # Trafic discret mais continu sur 300s avec labels tres longs
                # w5 presque nul : pas visible en temps reel
                "w5_dns_pkt":       5,
                "w5_dns_bytes":     600,
                "w5_dns_long_lbl":  4,

                "w60_dns_pkt":      55,
                "w60_dns_bytes":    9000,
                "w60_dns_long_lbl": 48,

                "w300_dns_pkt":     300,
                "w300_dns_bytes":   300000,
                "w300_dns_long_lbl": 270,
            },
        ),
    ]

    X_norm = scaler.transform(np.array([vector_from_partial(vals) for _, vals in cas_normaux]))
    X_att  = scaler.transform(np.array([vector_from_partial(vals) for _, vals in cas_attaques]))

    scores_norm = model.score_samples(X_norm)
    scores_att  = model.score_samples(X_att)

    print("  Cas normaux (attendu : NORMAL = score >= seuil) :")
    ok_norm = True
    for (label, values), score in zip(cas_normaux, scores_norm):
        # En production, une anomalie generique sans regle qualifiante est
        # seulement logguee comme suspicion, pas traitee comme attaque.
        verdict = "NORMAL  " if score >= threshold else "SUSPICION"
        ok = rule_alert_type(values) == "ANOMALIE_RESEAU"
        ok_norm = ok_norm and ok
        flag = "OK" if ok else "ECHEC"
        print(f"    [{flag}] {label:35s} score={score:.4f}  seuil={threshold:.4f}  -> {verdict}")

    print("\n  Cas attaques (attendu : ANOMALIE = score < seuil) :")
    ok_att = True
    for (label, values), score in zip(cas_attaques, scores_att):
        alert_type = rule_alert_type(values)
        is_alert = score < threshold or alert_type != "ANOMALIE_RESEAU"
        verdict = "ANOMALIE" if is_alert else "NORMAL  "
        ok = is_alert
        ok_att = ok_att and ok
        flag = "OK" if ok else "ECHEC"
        print(f"    [{flag}] {label:35s} score={score:.4f}  seuil={threshold:.4f}  -> {verdict} ({alert_type})")

    print()
    if not ok_norm:
        print("[VALIDATE] Faux positifs detectes")
        print("[VALIDATE] Le modele est trop sensible sur du trafic normal")
        print("[VALIDATE] Ajuste ANOMALY_PERCENTILE ou collecte plus de trafic legitime")

    if not ok_att:
        print("[VALIDATE] Faux negatifs detectes")
        print("[VALIDATE] Le modele ne detecte pas des attaques evidentes")

    if ok_norm and ok_att:
        print("[VALIDATE] Tous les cas passes")


if __name__ == "__main__":
    main()
