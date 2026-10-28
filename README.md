# Détection d'anomalies réseau - eBPF + Isolation Forest + N8N + Ollama

*Academic project - M1 Cryptis (Université de Limoges)*
*Co-authored with [DanySaft](https://github.com/DanySaft) and [carogrcl](https://github.com/carogrcl)*

> **Overview**: This project implements a real-time Intrusion Detection System (IDS). It uses eBPF/XDP to filter and collect network packets, an Isolation Forest model (Machine Learning) to detect anomalies, and an automated pipeline (N8N + Ollama LLM) to generate incident reports.

---

## Prérequis

- Ubuntu 22.04 / 24.04
- Docker installé et fonctionnel
- `python3`, `python3-venv`, `pip`
- `clang`, `llvm`, `libelf-dev`, `linux-tools-common` (pour eBPF)
- `npm` (pour le panel)
- Une machine externe sur le même réseau (Kali ou autre) pour les tests d'attaques et le training depuis l'extérieur

---

## 1. Premier setup

### 1.1 Créer le virtualenv Python

Depuis la racine du projet :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_training.txt
```

> Le venv doit être activé (`source .venv/bin/activate`) avant chaque commande Python du projet. Les prochaines étapes supposent qu'il est actif.

### 1.2 Lancer le setup

```bash
./setup_env.sh
```

Ce que ça fait :
- installe les dépendances système manquantes (bpftool, clang, etc.)
- crée le réseau Docker `ebpf-net`
- démarre les conteneurs N8N (port 5678) et Ollama
- télécharge le modèle LLM dans Ollama (`gemma3:4b`)
- démarre les conteneurs web-lab (nginx HTTP/HTTPS) et dns-lab (dnsmasq)
- attache la sonde XDP à l'interface réseau principale
- nettoie les logs temporaires

> Si le setup échoue sur `bpftool` :
> ```bash
> sudo apt install -y linux-tools-common linux-tools-$(uname -r)
> ```
> puis relancer `./setup_env.sh`.

### 1.3 Importer le workflow N8N

1. Ouvrir `http://localhost:5678` dans un navigateur
2. Créer un compte (première fois uniquement)
3. Aller dans **Workflows > Import from file**
4. Importer `scripts/n8n_workflow.json`
5. Ouvrir le workflow et cliquer **Activate** en haut à droite

---

## 2. Entraînement du modèle

> Le dépôt contient déjà un modèle entraîné dans `models/`, mais il a été entraîné sur notre propre réseau et machine. Les résultats peuvent donc être différents selon l'environnement. Pour tester seulement la détection, aller directement à la section 3.

L'entraînement nécessite de capturer du trafic réseau **normal** (pas d'attaques) depuis plusieurs sources simultanément, puis d'entraîner le modèle dessus.

### Étape 1 - Lancer la capture sur la VM

Dans un terminal sur la VM, avec le venv activé :

```bash
source .venv/bin/activate
python3 -m training.record_traffic
```

Laisser tourner. Il affiche le nombre de samples capturés toutes les 5 secondes. Arrêter avec Ctrl+C quand c'est fini (minimum 2-3 minutes, idéalement 15-20 min).

### Étape 2 - Générer du trafic depuis la VM (en parallèle)

Dans un **second terminal** sur la VM, pendant que `record_traffic` tourne :

```bash
bash training/generate_legit_traffic.sh
```

Ce script fait du trafic HTTP, HTTPS, DNS et ICMP synthétique depuis la VM vers internet et vers le web-lab local. Durée par défaut : 600s.

### Étape 3 - Générer du trafic depuis la machine externe (en parallèle)

Depuis une machine externe sur le même réseau (Kali ou autre), pendant que `record_traffic` tourne.

Si le script n'est pas déjà présent sur la machine externe, l'envoyer d'abord depuis la VM :

```bash
scp training/generation_traffic_machine_externe.sh <utilisateur>@<IP_machine_externe>:~/
```

Puis l'exécuter depuis la machine externe :

```bash
bash generation_traffic_machine_externe.sh <IP_VM> <utilisateur_ssh> <duree_en_minutes>
```

Exemple :
```bash
bash generation_traffic_machine_externe.sh <IP_VM> <utilisateur_ssh> 18
```

Ce script simule un utilisateur humain depuis l'extérieur : requêtes HTTP/HTTPS vers le web-lab de la VM, requêtes DNS, sessions SSH légitimes, petits téléchargements. Il faut que SSH soit accessible sur la VM avec clé ou mot de passe. La durée par défaut est 18 minutes.

### Étape 4 - Arrêter la capture et entraîner

Quand les scripts de trafic sont terminés (ou après suffisamment de temps), faire Ctrl+C dans le terminal de `record_traffic`.

Ensuite, sur la VM avec le venv activé :

```bash
python3 -m training.train_offline
```

Ça entraîne l'Isolation Forest, calcule le seuil, et sauvegarde les fichiers dans `models/`. Un rapport de validation s'affiche à la fin.

> Toujours sauvegarder les modèles avant de réentraîner :
> ```bash
> cp -r models models_backup
> ```

---

## 3. Lancer la détection

Avec le venv activé :

```bash
source .venv/bin/activate
python3 main.py
```

Le modèle se charge, la sonde XDP est déjà attachée depuis le setup, la détection démarre. Chaque itération de 5s affiche les IPs observées. Les alertes sont envoyées à N8N qui déclenche Ollama pour générer un rapport dans `rapports/`.

---

## 4. Panel de supervision

```bash
./start_panel.sh
```

- Frontend : `http://localhost:5173`
- Backend API : `http://localhost:8010`

Logs dans `logs/panel-backend.log` et `logs/panel-frontend.log`.

Arrêter le panel :

```bash
./stop_panel.sh
```

---

## 5. Tests d'attaques

Depuis la machine externe (remplacer `<IP>` par l'IP de la VM).

La détection doit tourner (`python3 main.py`) pendant les tests.

### Scan de ports

```bash
nmap <IP>
```

### SYN flood

```bash
sudo hping3 -S --flood -p 80 <IP>
```

### Brute force SSH

```bash
hydra -l root -P /usr/share/wordlists/rockyou.txt ssh://<IP>
```

### HTTP / HTTPS flood

```bash
ab -n 100000 -c 500 http://<IP>/
ab -n 100000 -c 500 -k https://<IP>/
```

### DNS burst

```bash
for i in $(seq 1 500); do dig @<IP> test$i.example.com; done
```

### DNS tunneling / exfiltration

```bash
for i in $(seq 1 300); do
  dig @<IP> $(python3 -c "import random,string; print(''.join(random.choices(string.ascii_lowercase,k=60)))").tunnel.example.com
  sleep 0.3
done
```

---

## 6. Débannir une IP manuellement

Si une IP est bannie mais n'apparaît plus dans le panel (ex: crash) :

```bash
# convertir l'IP en hex (ex: 192.168.1.186 -> c0 a8 01 ba)
python3 -c "import socket; print(' '.join(f'{b:02x}' for b in socket.inet_aton('192.168.1.186')))"

# supprimer de la map eBPF
sudo bpftool map delete name blacklist_map key hex c0 a8 01 ba
```

---

## 7. Arrêt complet

```bash
# arrêter le panel
./stop_panel.sh

# arrêter N8N, Ollama, web-lab, dns-lab et détacher la sonde XDP
./stop_env.sh
```

`stop_env.sh` supprime les conteneurs mais préserve les volumes Docker (modèles Ollama et workflows N8N sont gardés). Pour tout relancer : `./setup_env.sh`.

---

## Structure du projet

- `config/` - settings Python (chemins, URLs, etc.)
- `ebpf/` - code source C et binaire XDP compilé
- `ebpf_panel/` - panel web (frontend React + backend FastAPI)
- `logs/` - logs locaux, bans.json
- `models/` - modèle entraîné, scaler, seuil
- `rapports/` - rapports générés par N8N + Ollama
- `scripts/` - setup_env.sh + workflow N8N
- `src/` - collector, detector, ban_manager, main
- `training/` - scripts d'entraînement et de génération de trafic
- `web-lab/` - serveur nginx pour les tests HTTP/HTTPS
- `dns-lab/` - serveur DNS pour les tests DNS
- `main.py` - point d'entrée détection
- `setup_env.sh` - setup complet
- `start_panel.sh` - démarre le panel
- `stop_panel.sh` - arrête le panel
- `stop_env.sh` - arrête tout (conteneurs + sonde XDP)
