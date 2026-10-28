import fcntl
import json
import socket
import subprocess
import time
from contextlib import contextmanager

from fastapi import APIRouter
from pydantic import BaseModel


class UnbanRequest(BaseModel):
    sudo_password: str = ""

from app.core.settings import settings

router = APIRouter()


def _ip_to_hex(ip):
    return [f"{b:02x}" for b in socket.inet_aton(ip)]


def _bpftool_delete(ip, sudo_password=None):
    key = _ip_to_hex(ip)
    if sudo_password:
        # -k invalide le cache sudo pour forcer la verif du mot de passe saisi
        cmd = ["sudo", "-k", "-S", "bpftool", "map", "delete", "name", "blacklist_map", "key", "hex"] + key
        stdin_data = sudo_password + "\n"
    else:
        # -k invalide le cache : si l'utilisateur a un mdp il faudra le saisir
        # si il est NOPASSWD ca passe quand meme
        cmd = ["sudo", "-k", "bpftool", "map", "delete", "name", "blacklist_map", "key", "hex"] + key
        stdin_data = None
    try:
        r = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True, timeout=5, check=False)
        if r.returncode != 0:
            print(f"[PANEL] bpftool delete {ip} ECHEC : {r.stderr.strip() or r.stdout.strip()}")
        return r.returncode == 0
    except Exception as exc:
        print(f"[PANEL] bpftool delete {ip} exception : {exc}")
        return False


def _bans_file():
    return settings.resolved_logs_dir / "bans.json"


def _lock_file():
    return settings.resolved_logs_dir / "bans.lock"


@contextmanager
def _bans_lock():
    lf = _lock_file()
    lf.parent.mkdir(parents=True, exist_ok=True)
    with open(lf, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _load():
    f = _bans_file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(bans):
    f = _bans_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(bans, indent=2, ensure_ascii=False), encoding="utf-8")


@router.get("")
def list_bans():
    now = time.time()
    bans = _load()
    result = [
        {**info, "remaining": int(max(0.0, info["expires_at"] - now))}
        for info in bans.values()
    ]
    return sorted(result, key=lambda x: x["banned_at"], reverse=True)


@router.delete("/{ip}")
def unban(ip, body: UnbanRequest = None):
    password = (body.sudo_password or "") if body else ""

    # bpftool en premier : on ne touche pas bans.json si le déban échoue
    ok = _bpftool_delete(ip, sudo_password=password or None)

    if ok:
        with _bans_lock():
            bans = _load()
            bans.pop(ip, None)
            _save(bans)

    return {"ok": ok, "ip": ip, "bpftool": "ok" if ok else "echec sudo"}
