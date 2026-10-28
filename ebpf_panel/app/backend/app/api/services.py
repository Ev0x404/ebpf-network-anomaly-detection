import subprocess
import urllib.request
from fastapi import APIRouter
from app.core.settings import settings
from app.models.schemas import ServiceStatus

router = APIRouter()


def _check_http(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as _:
            return True
    except Exception:
        return False


def _docker_running(name):
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return name in result.stdout.splitlines()
    except Exception:
        return False


def _ollama_candidate_urls():
    """Même logique que chat.py : essaie localhost, hostname Docker, puis l'IP bridge."""
    candidates = [settings.ollama_url.rstrip("/"), "http://ollama:11434"]
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f",
             "{{range .NetworkSettings.Networks}}{{println .IPAddress}}{{end}}",
             settings.ollama_container],
            capture_output=True, text=True, timeout=2, check=False,
        )
        if result.returncode == 0:
            for ip in result.stdout.splitlines():
                ip = ip.strip()
                if ip:
                    candidates.append(f"http://{ip}:11434")
    except Exception:
        pass
    seen = []
    for u in candidates:
        if u and u not in seen:
            seen.append(u)
    return seen


def _check_ollama():
    """Retourne (running, url_qui_répond)."""
    for url in _ollama_candidate_urls():
        if _check_http(f"{url}/api/tags"):
            return True, url
    return False, settings.ollama_url


@router.get("/status", response_model=list[ServiceStatus])
def get_status():
    ollama_ok, ollama_url = _check_ollama()
    statuses = [
        ServiceStatus(name="n8n",          running=_check_http(settings.n8n_url), detail=settings.n8n_url),
        ServiceStatus(name="ollama",        running=ollama_ok,                     detail=ollama_url),
        ServiceStatus(name="docker:n8n",    running=_docker_running("n8n"),        detail="docker ps"),
        ServiceStatus(name="docker:ollama", running=_docker_running("ollama"),     detail="docker ps"),
    ]
    return statuses
