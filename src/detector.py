#!/usr/bin/env python3

import json
import time

import joblib
import numpy as np
import requests

from src.collector import FEATURE_COLS
from config.settings import (
    ALERTS_LOG,
    MODEL_FILE,
    N8N_WEBHOOK,
    SCALER_FILE,
    THRESHOLD_FILE,
)

# une fois une alerte levee pour une IP, on attend 60s avant d'en remettre une
# pour eviter le spam d'alertes sur la meme attaque
ALERT_COOLDOWN = 60


def _append_alert_log(alert):
    # ecrit l'alerte dans le fichier jsonl local (une alerte par ligne)
    try:
        ALERTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ALERTS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(alert) + "\n")
    except Exception:
        pass


class AnomalyDetector:
    def __init__(self):
        self.trained = False
        self.model = None
        self.scaler = None
        self.threshold = None
        self._last_alert = {}  # ip -> timestamp de la derniere alerte
        self._load()

    @staticmethod
    def _share(primary, *others):
        # proportion d'un service sur le total
        # ex: 80 ssh + 5 http + 0 https -> ssh_share = 80/85 = 0.94 (SSH dominant)
        total = primary + sum(others)
        return (primary / total) if total > 0 else 0.0

    def _load(self):
        # charge le modele, le scaler et le seuil depuis les fichiers generes
        # par train_offline.py
        try:
            self.scaler = joblib.load(SCALER_FILE)
            self.model = joblib.load(MODEL_FILE)

            with open(THRESHOLD_FILE, "r", encoding="utf-8") as fp:
                meta = json.load(fp)

            # verifie que les features du modele correspondent a celles du collector
            # si on a change FEATURE_COLS sans reentrainer ca planterait silencieusement
            if meta.get("feature_cols") != FEATURE_COLS:
                print("[DETECTOR] ERREUR : donnees incompatibles")
                print(f"[DETECTOR] Features du modele  : {meta.get('feature_cols')}")
                print(f"[DETECTOR] Features attendues  : {FEATURE_COLS}")
                print(
                    "[DETECTOR] Il faut reentrainer le model : "
                )
                return

            self.threshold = meta["threshold"]
            self.trained = True

            print(f"[DETECTOR] Modele charge ({meta['n_train_samples']} samples)")
            print(
                f"[DETECTOR] Seuil  : {self.threshold:.4f} "
                f"(p{meta['anomaly_percentile']} des scores d'entrainement)"
            )
            print(f"[DETECTOR] Cooldown : {ALERT_COOLDOWN}s par IP")

        except FileNotFoundError as e:
            print(f"[DETECTOR] Fichier manquant : {e}")
            print(
                "[DETECTOR] Il faut realiser l'entrainement du model Isolation Forest"
            )
        except Exception as e:
            print(f"[DETECTOR] Erreur : {e}")

    def _build_ssh_fast_alert(self, feat, score, margin=0.03):
        # fast path ssh : leve l'alerte meme si le score est juste en dessous
        # du seuil, tant que les metriques sont deja bien suspectes
        w5_ssh = feat["w5_connexions_ssh"]
        w60_ssh = feat["w60_connexions_ssh"]
        w5_http = feat["w5_connexions_http"]
        w60_http = feat["w60_connexions_http"]
        w5_https = feat["w5_connexions_https"]
        w60_https = feat["w60_connexions_https"]
        w5_ports = feat["w5_nb_ports"]
        w60_ports = feat["w60_nb_ports"]
        w5_syn = feat["w5_delta_syn"]
        w60_syn = feat["w60_delta_syn"]
        w5_syn_r = feat["w5_syn_ratio"]
        w60_syn_r = feat["w60_syn_ratio"]

        # "proche du seuil" = score un peu au dessus (pas encore une anomalie mais suspect)
        near_threshold = score < (self.threshold + margin)

        ssh_share_w5 = self._share(w5_ssh, w5_http, w5_https)
        ssh_share_w60 = self._share(w60_ssh, w60_http, w60_https)

        # SSH dominant sur 5s : beaucoup de connexions SSH, peu de HTTP/HTTPS
        ssh_dominant_w5 = (
            w5_ssh >= 8
            and w5_ssh >= 2 * (w5_http + w5_https)
            and ssh_share_w5 >= 0.70
        )

        # SSH dominant sur 60s : meme logique mais sur la fenetre plus large
        ssh_dominant_w60 = (
            w60_ssh >= 20
            and w60_ssh >= max(20, int(1.5 * (w60_http + w60_https)))
            and ssh_share_w60 >= 0.60
            and w5_ssh >= 2
        )

        if near_threshold and ssh_dominant_w5 and w5_ports <= 1 and w5_syn >= 4 and w5_syn_r <= 0.35:
            return self._alert(
                feat, score, "BRUTE_FORCE_SSH_SUSPECT", "high",
                f"fast-path ssh : w5_ssh={w5_ssh}, w60_ssh={w60_ssh}, "
                f"w5_syn={w5_syn}, http5={w5_http}, https5={w5_https}, "
                f"score={score:.4f}, seuil={self.threshold:.4f}",
            )

        if near_threshold and ssh_dominant_w60 and w60_ports <= 1 and w60_syn >= 8 and w60_syn_r <= 0.25:
            return self._alert(
                feat, score, "BRUTE_FORCE_SSH_SUSPECT", "high",
                f"fast-path ssh : w60_ssh={w60_ssh}, w60_syn={w60_syn}, http60={w60_http}, "
                f"https60={w60_https}, score={score:.4f}, seuil={self.threshold:.4f}",
            )

        return None

    def _build_dns_fast_alert(self, feat, score, margin=0.05):
        # meme principe que pour SSH mais pour les attaques DNS qui passent juste sous le seuil
        near_threshold = score < (self.threshold + margin)

        w5_dns_pkt = feat["w5_dns_pkt"]

        w60_dns_pkt = feat["w60_dns_pkt"]
        w60_dns_bytes = feat["w60_dns_bytes"]
        w60_dns_avg_size = feat["w60_dns_avg_size"]
        w60_dns_large_ratio = feat["w60_dns_large_ratio"]

        w300_dns_pkt = feat["w300_dns_pkt"]
        w300_dns_bytes = feat["w300_dns_bytes"]
        w300_dns_avg_size = feat["w300_dns_avg_size"]
        w300_dns_large_ratio = feat["w300_dns_large_ratio"]

        # burst : trop de paquets DNS en peu de temps
        if near_threshold and (w5_dns_pkt > 200 or w60_dns_pkt > 1500):
            return self._alert(
                feat, score, "DNS_BURST_SUSPECT", "high",
                f"fast-path dns burst : w5_dns_pkt={w5_dns_pkt}, "
                f"w60_dns_pkt={w60_dns_pkt}, score={score:.4f}, seuil={self.threshold:.4f}",
            )

        # tunneling : paquets grands (labels longs = donnees encodees dans le nom de domaine)
        if (
            near_threshold
            and w60_dns_pkt > 80
            and w60_dns_large_ratio > 0.55
            and w60_dns_avg_size > 100
        ):
            return self._alert(
                feat, score, "DNS_TUNNELING_SUSPECT", "high",
                f"fast-path dns tunneling : w60_dns_pkt={w60_dns_pkt}, "
                f"w60_dns_bytes={w60_dns_bytes}, large_ratio={w60_dns_large_ratio:.2f}, "
                f"avg_size={w60_dns_avg_size:.1f}, score={score:.4f}, seuil={self.threshold:.4f}",
            )

        # exfiltration lente : meme principe mais sur 5 minutes
        if (
            near_threshold
            and w300_dns_pkt > 180
            and w300_dns_bytes > 200000
            and w300_dns_large_ratio > 0.20
            and w300_dns_avg_size > 110
            and w60_dns_pkt > 15
        ):
            return self._alert(
                feat, score, "DNS_EXFILTRATION_SUSPECT", "medium",
                f"fast-path dns exfil : w300_dns_pkt={w300_dns_pkt}, "
                f"w300_dns_bytes={w300_dns_bytes}, large_ratio300={w300_dns_large_ratio:.2f}, "
                f"avg_size300={w300_dns_avg_size:.1f}, score={score:.4f}, seuil={self.threshold:.4f}",
            )

        return None

    def detect(self, features_list):
        if not self.trained or not features_list:
            return []

        # on normalise les valeurs avec le scaler, puis le modele calcule un score par IP
        X = np.array([[f[c] for c in FEATURE_COLS] for f in features_list])
        X_sc = self.scaler.transform(X)
        scores = self.model.score_samples(X_sc)

        now = time.time()
        anomalies = []

        for feat, score in zip(features_list, scores):
            score = float(score)

            # on calcule les trois types d'alertes possibles
            rule_alert = self._build_alert(feat, score)
            ssh_fast_alert = self._build_ssh_fast_alert(feat, score, margin=0.03)
            dns_fast_alert = self._build_dns_fast_alert(feat, score, margin=0.05)

            # si le score est normal ET qu'aucune regle specifique ne matche
            # ET qu'aucun fast path ne s'est declenche -> on ignore
            if (
                score >= self.threshold
                and rule_alert["type"] == "ANOMALIE_RESEAU"
                and ssh_fast_alert is None
                and dns_fast_alert is None
            ):
                continue

            ip = feat["src_ip"]
            # on respecte le cooldown pour ne pas spam la meme IP
            last = self._last_alert.get(ip, 0)
            if now - last < ALERT_COOLDOWN:
                continue

            # priorite : fast path SSH > fast path DNS > regles generiques
            alert = ssh_fast_alert or dns_fast_alert or rule_alert

            if alert["type"] != "ANOMALIE_RESEAU":
                # alerte reelle : on ban et on envoie a n8n
                self._last_alert[ip] = now
                anomalies.append(alert)
                print(
                    f"[DETECTOR] ALERTE   : {ip:16s} | "
                    f"type={alert['type']:30s} | "
                    f"sev={alert['severity']:6s} | "
                    f"score={score:.4f} < seuil={self.threshold:.4f}"
                )
            else:
                # c'est juste "bizarre" selon l'Isolation Forest mais aucune regle ne matche -> log sans ban
                print(
                    f"[DETECTOR] SUSPICION: {ip:16s} | "
                    f"score={score:.4f} | "
                    f"w60_conx={feat['w60_delta_connexions']} "
                    f"w60_rst={feat['w60_delta_rst']} "
                    f"w60_syn_r={feat['w60_syn_ratio']:.2f} | "
                    f"ssh60={feat['w60_connexions_ssh']} "
                    f"http60={feat['w60_connexions_http']} "
                    f"https60={feat['w60_connexions_https']} "
                    f"dns60={feat['w60_dns_pkt']} "
                    f"dns60_ratio={feat['w60_dns_large_ratio']:.2f} "
                    f"dns60_avg={feat['w60_dns_avg_size']:.1f}"
                )

                _append_alert_log({**alert, "logged_only": True})

        return anomalies

    def _build_alert(self, feat, score):
        # recupere les metriques sur les 3 fenetres de temps
        w5_ports = feat["w5_nb_ports"]
        w5_syn_r = feat["w5_syn_ratio"]
        w5_syn = feat["w5_delta_syn"]

        w60_ports = feat["w60_nb_ports"]
        w60_syn = feat["w60_delta_syn"]
        w60_syn_r = feat["w60_syn_ratio"]
        w60_rst = feat["w60_delta_rst"]

        w300_ports = feat["w300_nb_ports"]
        w300_syn_r = feat["w300_syn_ratio"]
        w300_rst = feat["w300_delta_rst"]

        w5_ssh = feat["w5_connexions_ssh"]
        w60_ssh = feat["w60_connexions_ssh"]
        w300_ssh = feat["w300_connexions_ssh"]

        w5_http = feat["w5_connexions_http"]
        w60_http = feat["w60_connexions_http"]
        w300_http = feat["w300_connexions_http"]

        w5_https = feat["w5_connexions_https"]
        w60_https = feat["w60_connexions_https"]
        w300_https = feat["w300_connexions_https"]

        w5_dns_pkt = feat["w5_dns_pkt"]

        w60_dns_pkt = feat["w60_dns_pkt"]
        w60_dns_bytes = feat["w60_dns_bytes"]
        w60_dns_avg_size = feat["w60_dns_avg_size"]
        w60_dns_large_ratio = feat["w60_dns_large_ratio"]

        w300_dns_pkt = feat["w300_dns_pkt"]
        w300_dns_bytes = feat["w300_dns_bytes"]
        w300_dns_avg_size = feat["w300_dns_avg_size"]
        w300_dns_large_ratio = feat["w300_dns_large_ratio"]

        # proportion de chaque service par rapport aux autres
        ssh_share_w60 = self._share(w60_ssh, w60_http, w60_https)
        ssh_share_w300 = self._share(w300_ssh, w300_http, w300_https)
        http_share_w60 = self._share(w60_http, w60_ssh, w60_https)
        http_share_w300 = self._share(w300_http, w300_ssh, w300_https)
        https_share_w60 = self._share(w60_https, w60_ssh, w60_http)
        https_share_w300 = self._share(w300_https, w300_ssh, w300_http)

        # SSH dominant = beaucoup de connexions SSH par rapport au reste
        ssh_dominant_w60 = (
            w60_ssh >= 40
            and w60_ssh >= max(40, int(1.5 * (w60_http + w60_https)))
            and ssh_share_w60 >= 0.60
            and w5_ssh >= 2
        )
        ssh_dominant_w300 = (
            w300_ssh >= 120
            and w300_ssh >= max(120, int(1.5 * (w300_http + w300_https)))
            and ssh_share_w300 >= 0.60
            and w60_ssh >= 15
        )

        http_dominant_w60 = (
            w60_http >= 80
            and w60_http >= max(80, int(1.2 * (w60_ssh + w60_https)))
            and http_share_w60 >= 0.55
            and w5_http >= 5
        )
        http_dominant_w300 = (
            w300_http >= 200
            and w300_http >= max(200, int(1.2 * (w300_ssh + w300_https)))
            and http_share_w300 >= 0.55
            and w60_http >= 40
        )

        https_dominant_w60 = (
            w60_https >= 100
            and w60_https >= max(100, int(1.2 * (w60_ssh + w60_http)))
            and https_share_w60 >= 0.55
            and w5_https >= 5
        )
        https_dominant_w300 = (
            w300_https >= 250
            and w300_https >= max(250, int(1.2 * (w300_ssh + w300_http)))
            and https_share_w300 >= 0.55
            and w60_https >= 50
        )

        # regles de qualification, du plus specifique au plus general

        total_ports = feat.get("total_distinct_ports", 0)
        w5_conx = feat["w5_delta_connexions"]

        # SYN flood concentre sur un port de service (ex: hping3 -S -p 80 --flood)
        # nmap envoie 1-10 paquets par port donc max_service_conx reste faible
        # hping3 envoie des milliers sur le meme port donc max_service_conx explose
        max_service_conx = max(w5_http, w5_ssh, w5_https)
        if w5_syn_r > 0.85 and w5_ports <= 3 and max_service_conx > 20:
            return self._alert(
                feat, score, "DOS_SYN_FLOOD", "high",
                f"flood service : port_conx={max_service_conx}, w5_syn={w5_syn}, syn_r={w5_syn_r:.2f}"
            )

        # SYN flood haute frequence sur port non standard
        # conn_map compte tous les paquets TCP donc un HTTP flood (ab -c 500)
        # peut avoir w5_conx > 50k mais avec syn_ratio bas (~0.17)
        # on exige syn_ratio > 0.85 pour ne pas confondre avec un flood HTTP
        if w5_conx > 50000 and w5_syn > 1000 and w5_ports <= 3 and w5_syn_r > 0.85:
            return self._alert(
                feat, score, "DOS_SYN_FLOOD", "high",
                f"flood brut : w5_conx={w5_conx}, w5_syn={w5_syn}, port(s)={w5_ports}"
            )

        # scan de ports rapide : beaucoup de nouveaux ports en 5s avec que des SYN
        if w5_ports > 20 and w5_syn_r > 0.7:
            return self._alert(
                feat, score, "PORT_SCAN_RAPIDE", "high",
                f"w5: {w5_ports} ports, syn_ratio={w5_syn_r}"
            )

        # scan SYN agressif : beaucoup de SYN sur peu de ports avec des RST en retour
        # w5_conx <= 10000 pour ne pas confondre avec un flood
        if w5_syn > 100 and w5_syn_r > 0.85 and w5_ports <= 3 and w60_rst > 10 and w5_conx <= 10000:
            return self._alert(
                feat, score, "PORT_SCAN_RAPIDE", "high",
                f"scan SYN probable : w5_syn={w5_syn}, w5_ports={w5_ports}, w60_rst={w60_rst}"
            )

        # rescan : conn_map est cumulative donc apres un premier scan new_ports = 0
        # mais total_distinct_ports montre quand meme qu'il y a eu beaucoup de ports
        if w5_syn > 100 and w5_syn_r > 0.85 and w5_ports <= 3 and total_ports > 50 and w5_conx <= 10000:
            return self._alert(
                feat, score, "PORT_SCAN_RAPIDE", "high",
                f"{total_ports} ports scannes, w5_syn={w5_syn}, w60_rst={w60_rst}"
            )

        # DoS SYN : meme signature que scan mais sans RST en retour (IP fraiche ou debit eleve)
        # on parle de DoS car c'est une seule IP source, un DDoS viendrait de plusieurs
        if w5_syn > 100 and w5_syn_r > 0.85 and w5_ports <= 3 and w60_rst <= 10 and (total_ports <= 50 or w5_conx > 10000):
            return self._alert(
                feat, score, "DOS_SYN_FLOOD", "high",
                f"w5: {w5_syn} SYN, {w5_ports} port(s), w60_rst={w60_rst}"
            )

        # DNS burst : trop de paquets DNS en peu de temps
        if w5_dns_pkt > 200 or w60_dns_pkt > 1500:
            return self._alert(
                feat, score, "DNS_BURST_SUSPECT", "high",
                f"w5_dns_pkt={w5_dns_pkt}, w60_dns_pkt={w60_dns_pkt}"
            )

        # DNS tunneling : labels longs = donnees encodees dans les noms de domaine
        # avg_size > 110 bytes et large_ratio > 0.60 = la majorite des requetes sont suspectes
        if (
            w60_dns_pkt > 100
            and w60_dns_large_ratio > 0.60
            and w60_dns_avg_size > 110
        ):
            return self._alert(
                feat, score, "DNS_TUNNELING_SUSPECT", "high",
                f"w60_dns_pkt={w60_dns_pkt}, w60_dns_bytes={w60_dns_bytes}, "
                f"large_ratio={w60_dns_large_ratio:.2f}, avg_size={w60_dns_avg_size:.1f}"
            )

        # exfiltration DNS lente : meme principe mais etalee sur 5 minutes
        if (
            w300_dns_pkt > 250
            and w300_dns_bytes > 250000
            and w300_dns_large_ratio > 0.25
            and w300_dns_avg_size > 120
            and w60_dns_pkt > 20
        ):
            return self._alert(
                feat, score, "DNS_EXFILTRATION_SUSPECT", "medium",
                f"w300_dns_pkt={w300_dns_pkt}, w300_dns_bytes={w300_dns_bytes}, "
                f"large_ratio300={w300_dns_large_ratio:.2f}, avg_size300={w300_dns_avg_size:.1f}"
            )

        # tunneling lent : volume sur 5 min mais ratio eleve (tunnel actif a faible debit)
        if (
            w300_dns_pkt > 300
            and w60_dns_pkt > 50
            and w300_dns_large_ratio > 0.50
            and w300_dns_avg_size > 110
        ):
            return self._alert(
                feat, score, "DNS_TUNNELING_LENT_SUSPECT", "medium",
                f"w300_dns_pkt={w300_dns_pkt}, w60_dns_pkt={w60_dns_pkt}, "
                f"large_ratio300={w300_dns_large_ratio:.2f}, avg_size300={w300_dns_avg_size:.1f}"
            )

        # HTTP flood : connexions completees (syn_ratio bas) concentrees sur port 80
        if http_dominant_w60 and w60_syn_r <= 0.35:
            return self._alert(
                feat, score, "HTTP_FLOOD_SUSPECT", "high",
                f"w60_http={w60_http}, ssh60={w60_ssh}, https60={w60_https}, "
                f"http_share60={http_share_w60:.2f}, syn_ratio={w60_syn_r}"
            )

        if http_dominant_w300 and w300_syn_r <= 0.35:
            return self._alert(
                feat, score, "HTTP_FLOOD_LENT_SUSPECT", "medium",
                f"w300_http={w300_http}, w60_http={w60_http}, ssh300={w300_ssh}, "
                f"https300={w300_https}, http_share300={http_share_w300:.2f}, "
                f"syn_ratio={w300_syn_r}"
            )

        # HTTPS flood : meme chose mais sur port 443
        if https_dominant_w60 and w60_syn_r <= 0.35:
            return self._alert(
                feat, score, "HTTPS_FLOOD_SUSPECT", "high",
                f"w60_https={w60_https}, ssh60={w60_ssh}, http60={w60_http}, "
                f"https_share60={https_share_w60:.2f}, syn_ratio={w60_syn_r}"
            )

        if https_dominant_w300 and w300_syn_r <= 0.35:
            return self._alert(
                feat, score, "HTTPS_FLOOD_LENT_SUSPECT", "medium",
                f"w300_https={w300_https}, w60_https={w60_https}, ssh300={w300_ssh}, "
                f"http300={w300_http}, https_share300={https_share_w300:.2f}, "
                f"syn_ratio={w300_syn_r}"
            )

        # brute force SSH : beaucoup de connexions SSH mais syn_ratio bas
        # (les connexions se completent, c'est pas du SYN flood)
        if ssh_dominant_w60 and w60_syn >= 8 and w60_syn_r <= 0.25:
            return self._alert(
                feat, score, "BRUTE_FORCE_SSH_SUSPECT", "high",
                f"w60_ssh={w60_ssh}, http60={w60_http}, https60={w60_https}, "
                f"ssh_share60={ssh_share_w60:.2f}, w60_syn={w60_syn}, syn_ratio={w60_syn_r}, rst={w60_rst}"
            )

        if ssh_dominant_w300 and w60_syn >= 5 and w300_syn_r <= 0.25:
            return self._alert(
                feat, score, "BRUTE_FORCE_SSH_LENT_SUSPECT", "medium",
                f"w300_ssh={w300_ssh}, w60_ssh={w60_ssh}, http300={w300_http}, "
                f"https300={w300_https}, ssh_share300={ssh_share_w300:.2f}, "
                f"w60_syn={w60_syn}, syn_ratio={w300_syn_r}, rst={w300_rst}"
            )

        # brute force generique : beaucoup de RST sur peu de ports
        # les RST viennent des echecs d'authentification
        if (
            w60_rst > 50
            and w60_ports <= 3
            and w60_syn >= 8
            and w60_syn_r < 0.5
            and (w60_ssh >= max(10, w60_http, w60_https) or (w60_http + w60_https) < 20)
        ):
            return self._alert(
                feat, score, "BRUTE_FORCE_RAPIDE", "high",
                f"w60: {w60_rst} RST, {w60_ports} port(s)"
            )

        # scan modere : ports vus sur 60s mais pas sur les 5 dernieres secondes
        # = scan qui s'etale dans le temps pour passer sous les radars
        if w60_ports > 30 and w5_ports < 10 and w60_syn_r > 0.6:
            return self._alert(
                feat, score, "PORT_SCAN_MODERE", "medium",
                f"w60: {w60_ports} ports, w5: {w5_ports} ports"
            )

        # scan tres lent : meme idee mais sur 5 minutes (ex: nmap -T1 ou -T2)
        if w300_ports > 50 and w5_ports < 5 and w300_syn_r > 0.4:
            return self._alert(
                feat, score, "PORT_SCAN_LENT", "medium",
                f"w300: {w300_ports} ports, w5: {w5_ports} ports"
            )

        # brute force lent : RST accumules sur 5 minutes
        if (
            w300_rst > 80
            and w300_ports <= 3
            and (w300_ssh >= max(20, w300_http, w300_https) or (w300_http + w300_https) < 40)
            and w60_syn >= 5
            and w60_ssh >= 5
        ):
            return self._alert(
                feat, score, "BRUTE_FORCE_LENT", "medium",
                f"w300: {w300_rst} RST, {w300_ports} port(s)"
            )

        # rien ne correspond mais Isolation Forest trouve ca quand meme bizarre -> log sans ban
        return self._alert(
            feat, score, "ANOMALIE_RESEAU", "medium",
            f"score={score:.4f} sous seuil={self.threshold:.4f}"
        )

    def _alert(self, feat, score, attack_type, severity, detail):
        # construit le dictionnaire d'alerte avec toutes les infos utiles
        return {
            "type": attack_type,
            "src_ip": feat["src_ip"],
            "severity": severity,
            "detail": detail,
            "score": round(score, 4),
            "threshold": round(self.threshold, 4),
            "metriques": {c: feat[c] for c in FEATURE_COLS},
            "timestamp": feat["timestamp"],
        }


def send_alert_to_n8n(alert):
    # envoie l'alerte a n8n pour declencher ollama, log local au cas ou ca ne repond pas
    _append_alert_log(alert)

    try:
        resp = requests.post(N8N_WEBHOOK, json=alert, timeout=5)
        if resp.status_code in (200, 201):
            print(f"[DETECTOR] Alerte envoyee a N8N  ({resp.status_code})")
            return True

        print(f"[DETECTOR] N8N a repondu {resp.status_code}")
        return False

    except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as e:
        print(
            f"[DETECTOR] N8N indisponible ou trop lent ({type(e).__name__}) "
            f"- log : {ALERTS_LOG}"
        )
        return False
