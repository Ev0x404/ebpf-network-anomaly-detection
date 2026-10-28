#!/usr/bin/env python3
"""
Enregistrement du trafic normal pour l'entrainement offline.
"""

import json
import time
from datetime import datetime

from config.settings import NORMAL_TRAFFIC_FILE
from src.collector import FEATURE_COLS, collect_features, reset_state

INTERVAL = 5
NORMAL_TRAFFIC_FILE.parent.mkdir(parents=True, exist_ok=True)


def main():
    reset_state()
    all_features = []

    print("[RECORD] Enregistrement du trafic normal")
    print("[RECORD] Fais du trafic classique : navigation, ping, curl, etc.")
    print("[RECORD] Le premier cycle est toujours ignore (calcul des deltas)")
    print("[RECORD] Ctrl+C quand tu as assez de trafic (minimum 2-3 minutes)\n")

    first_cycle = True

    try:
        while True:
            feats = collect_features()

            if first_cycle:
                first_cycle = False
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Premier cycle ignore (initialisation des deltas)")
                time.sleep(INTERVAL)
                continue

            if feats:
                all_features.extend(feats)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {len(feats):3d} IP(s) — total : {len(all_features)} samples")

            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        print(f"\n[RECORD] Arret — {len(all_features)} samples enregistres")
        if len(all_features) < 50:
            print("[RECORD] Attention : peu de samples. Le modele sera moins fiable. Idealement >= 500.")

        serializable = []
        for f in all_features:
            entry = {c: f[c] for c in FEATURE_COLS}
            entry["src_ip"] = f["src_ip"]
            entry["timestamp"] = f["timestamp"]
            serializable.append(entry)

        with open(NORMAL_TRAFFIC_FILE, "w", encoding="utf-8") as fp:
            json.dump(serializable, fp, indent=2)

        print(f"[RECORD] Sauvegarde dans {NORMAL_TRAFFIC_FILE}")
        print("[RECORD] Lance maintenant : python3 train_offline.py")


if __name__ == "__main__":
    main()
