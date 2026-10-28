#!/usr/bin/env python3

import fcntl
import json
import socket
import subprocess
import time
from contextlib import contextmanager

from config.settings import LOGS_DIR

BANS_FILE = LOGS_DIR / "bans.json"
_LOCK_FILE = LOGS_DIR / "bans.lock"
BAN_DURATION = 300  # en secondes


# verrou fichier pour eviter les conflits entre main.py et le panel FastAPI
# qui peuvent tous les deux lire/ecrire bans.json en meme temps
@contextmanager
def _bans_lock():
    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOCK_FILE, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _ip_to_hex(ip):
    # bpftool attend la cle en hex big-endian, donc on convertit chaque octet
    return [f"{b:02x}" for b in socket.inet_aton(ip)]


def _bpftool(op, ip):
    # on construit la commande bpftool selon l'operation voulue (update = ban, delete = deban)
    key = _ip_to_hex(ip)
    if op == "update":
        cmd = (["sudo", "bpftool", "map", "update", "name", "blacklist_map",
                "key", "hex"] + key + ["value", "hex", "01"])
    else:
        cmd = (["sudo", "bpftool", "map", "delete", "name", "blacklist_map",
                "key", "hex"] + key)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
        if r.returncode != 0:
            print(f"[BAN] bpftool {op} {ip} : {r.stderr.strip() or r.stdout.strip()}")
        return r.returncode == 0
    except Exception as exc:
        print(f"[BAN] bpftool {op} {ip} exception : {exc}")
        return False


def _load():
    # si le fichier n'existe pas encore on retourne un dictionnaire vide
    if not BANS_FILE.exists():
        return {}
    try:
        return json.loads(BANS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(bans):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    BANS_FILE.write_text(
        json.dumps(bans, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def ban_ip(ip, duration=BAN_DURATION, reason="", attack_type=""):
    now = time.time()
    # on met a jour la map eBPF
    with _bans_lock():
        bans = _load()
        bans[ip] = {
            "ip": ip,
            "banned_at": now,
            "expires_at": now + duration,
            "duration": duration,
            "reason": reason,
            "attack_type": attack_type,
        }
        _save(bans)
    ok = _bpftool("update", ip)
    print(f"[BAN] BAN    {ip:16s} | {attack_type} | {duration}s | {'OK' if ok else 'ECHEC bpftool'}")
    return ok


def unban_ip(ip):
    with _bans_lock():
        bans = _load()
        bans.pop(ip, None)
        _save(bans)
    ok = _bpftool("delete", ip)
    print(f"[BAN] UNBAN  {ip:16s} | {'OK' if ok else 'ECHEC bpftool'}")
    return ok


def cleanup_expired():
    now = time.time()
    # D'abord on nettoie le JSON sous verrou, ensuite on appelle bpftool hors du verrou 
    with _bans_lock():
        bans = _load()
        expired = [ip for ip, info in bans.items() if info["expires_at"] <= now]
        for ip in expired:
            del bans[ip]
        if expired:
            _save(bans)
    for ip in expired:
        _bpftool("delete", ip)
        print(f"[BAN] EXPIRE {ip}")
    return expired


def list_bans():
    # calcule le temps restant pour chaque ban
    now = time.time()
    return sorted(
        [{**info, "remaining": int(max(0.0, info["expires_at"] - now))}
         for info in _load().values()],
        key=lambda x: x["banned_at"],
        reverse=True,
    )
