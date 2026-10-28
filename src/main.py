#!/usr/bin/env python3

import sys
import time
import signal
from datetime import datetime

from src.collector import collect_features, reset_state, reset_ip_state
from src.detector import AnomalyDetector, send_alert_to_n8n
from src.ban_manager import ban_ip, cleanup_expired

# toutes les 5s on relit les maps eBPF
COLLECT_INTERVAL = 5  # secondes


def main():
    print("=" * 60)
    print("  Detection d'Anomalies Reseau - eBPF + IA")
    print("  Master 1 Cryptis - HEMERY / BRULARD / GOURCEYROL")
    print("=" * 60)

    # on charge le modele Isolation Forest, si pas dispo on arrete tout
    detector = AnomalyDetector()
    if not detector.trained:
        print("[MAIN] Arret : modele Isolation Forest non charge.")
        sys.exit(1)

    # remet les maps a zero pour partir d'un etat propre
    reset_state()

    print("\n[MAIN] Detection en temps reel - Ctrl+C pour arreter\n")

    # gestion propre du Ctrl+C
    def on_exit(sig, frame):
        print("\n[MAIN] Arret propre.")
        sys.exit(0)

    signal.signal(signal.SIGINT, on_exit)

    iteration = 0
    first_cycle = True

    while True:
        feats = collect_features()
        iteration += 1
        ts = datetime.now().strftime("%H:%M:%S")

        # le premier cycle sert juste a initialiser les deltas (pas de detection)
        if first_cycle:
            first_cycle = False
            print(f"[{ts}] Iter {iteration:04d} - initialisation des deltas")
            time.sleep(COLLECT_INTERVAL)
            continue

        if feats:
            print(f"[{ts}] Iter {iteration:04d} - {len(feats)} IP(s) observees")
            anomalies = detector.detect(feats)
            for alert in anomalies:
                # envoie l'alerte a N8N qui declenche Ollama pour le rapport
                send_alert_to_n8n(alert)
                ban_ip(
                    alert["src_ip"],
                    reason=alert.get("detail", ""),
                    attack_type=alert.get("type", ""),
                )
                # on remet a zero l'historique de l'IP bannie pour eviter
                # que les anciennes metriques de l'attaque contaminent la suite
                reset_ip_state(alert["src_ip"])
        else:
            print(f"[{ts}] Iter {iteration:04d} - aucune IP observee")

        # leve les bans expires automatiquement
        cleanup_expired()
        time.sleep(COLLECT_INTERVAL)


if __name__ == "__main__":
    main()
