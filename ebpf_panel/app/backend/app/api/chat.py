import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.settings import settings

router = APIRouter()

# stockage des conversations dans data/ a cote du backend
_DATA_DIR  = Path(__file__).resolve().parent.parent / "data"
_CONV_FILE = _DATA_DIR / "conversations.json"
_DATA_LOCK = threading.Lock()


def _load():
    if not _CONV_FILE.exists():
        return {}
    try:
        return json.loads(_CONV_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data):
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = _CONV_FILE.with_name(f"{_CONV_FILE.name}.{uuid.uuid4().hex}.tmp")
    tmp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(_CONV_FILE)


class ChatRequest(BaseModel):
    message: str
    model: str | None = None


class ChatResponse(BaseModel):
    response: str
    model: str


class ConversationMeta(BaseModel):
    id: str
    title: str
    created_at: float
    updated_at: float
    message_count: int


class MessageIn(BaseModel):
    content: str
    model: str | None = None


def _candidate_ollama_urls():
    # essaie plusieurs URLs pour joindre Ollama : localhost, nom Docker, puis IP bridge
    urls = [settings.ollama_url.rstrip("/")]
    urls.append("http://ollama:11434")
    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{range .NetworkSettings.Networks}}{{println .IPAddress}}{{end}}",
                settings.ollama_container,
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            for ip in result.stdout.splitlines():
                ip = ip.strip()
                if ip:
                    urls.append(f"http://{ip}:11434")
    except Exception:
        pass

    deduped = []
    for url in urls:
        if url and url not in deduped:
            deduped.append(url)
    return deduped


async def _ollama_request(method, path, continue_on_statuses=None, **kwargs):
    errors = []
    continue_on_statuses = continue_on_statuses or set()
    async with httpx.AsyncClient(timeout=kwargs.pop("timeout", 120)) as client:
        for base_url in _candidate_ollama_urls():
            try:
                resp = await client.request(method, f"{base_url}{path}", **kwargs)
                resp.raise_for_status()
                return resp, base_url
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:300] if exc.response.text else ""
                if exc.response.status_code in continue_on_statuses:
                    errors.append(f"{base_url}: HTTP {exc.response.status_code} {detail}".strip())
                    continue
                raise HTTPException(
                    status_code=502,
                    detail=f"Ollama sur {base_url} a renvoyé {exc.response.status_code}. {detail}",
                )
            except httpx.RequestError as exc:
                errors.append(f"{base_url}: {exc.__class__.__name__}")

    raise HTTPException(
        status_code=502,
        detail=(
            "Impossible de joindre Ollama/Gemma. URLs essayées: "
            f"{', '.join(_candidate_ollama_urls())}. "
            f"Détails: {'; '.join(errors) if errors else 'aucun détail'}. "
            "Vérifie que le conteneur 'ollama' tourne ou publie le port 11434."
        ),
    )


async def _ollama(prompt, model):
    payload = {"model": model, "prompt": prompt, "stream": False}
    try:
        resp, _ = await _ollama_request(
            "POST",
            "/api/generate",
            continue_on_statuses={404},
            json=payload,
        )
        return resp.json().get("response", "")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erreur Ollama : {exc}")


@router.get("/models")
async def list_models():
    errors = []
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            for base_url in _candidate_ollama_urls():
                try:
                    resp = await client.get(f"{base_url}/api/tags")
                    resp.raise_for_status()
                    data = resp.json()
                    names = [m["name"] for m in data.get("models", [])]
                    if names:
                        return names
                    errors.append(f"{base_url}: aucun modèle")
                except httpx.RequestError as exc:
                    errors.append(f"{base_url}: {exc.__class__.__name__}")
                except httpx.HTTPStatusError as exc:
                    errors.append(f"{base_url}: HTTP {exc.response.status_code}")
        return []
    except Exception as exc:
        detail = str(exc)
        if errors:
            detail = f"{detail}. URLs essayées: {', '.join(errors)}"
        raise HTTPException(status_code=502, detail=detail)


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    model = request.model or settings.ollama_model
    response = await _ollama(request.message, model)
    return ChatResponse(response=response, model=model)


@router.get("/conversations", response_model=list[ConversationMeta])
def list_conversations():
    with _DATA_LOCK:
        data = _load()
    convs = list(data.values())
    convs.sort(key=lambda c: c["updated_at"], reverse=True)
    return [
        ConversationMeta(
            id=c["id"],
            title=c["title"],
            created_at=c["created_at"],
            updated_at=c["updated_at"],
            message_count=len(c["messages"]),
        )
        for c in convs
    ]


@router.post("/conversations", response_model=ConversationMeta, status_code=201)
def create_conversation():
    with _DATA_LOCK:
        data = _load()
        cid  = str(uuid.uuid4())
        now  = time.time()
        conv = {
            "id": cid,
            "title": "Nouvelle conversation",
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        data[cid] = conv
        _save(data)
    return ConversationMeta(id=cid, title=conv["title"],
                            created_at=now, updated_at=now, message_count=0)


@router.get("/conversations/{cid}")
def get_conversation(cid):
    with _DATA_LOCK:
        data = _load()
    if cid not in data:
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    return data[cid]


@router.delete("/conversations/{cid}")
def delete_conversation(cid):
    with _DATA_LOCK:
        data = _load()
        if cid in data:
            del data[cid]
            _save(data)
    return {"ok": True}


@router.put("/conversations/{cid}/title")
def rename_conversation(cid, body: dict):
    with _DATA_LOCK:
        data = _load()
        if cid not in data:
            raise HTTPException(status_code=404, detail="Conversation introuvable.")
        data[cid]["title"] = body.get("title", data[cid]["title"])[:80]
        data[cid]["updated_at"] = time.time()
        _save(data)
    return {"ok": True}


@router.post("/conversations/{cid}/message")
async def send_message(cid, body: MessageIn):
    model   = body.model or settings.ollama_model
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message vide.")

    with _DATA_LOCK:
        data = _load()
        if cid not in data:
            raise HTTPException(status_code=404, detail="Conversation introuvable.")
        history = list(data[cid]["messages"][-10:])

    ctx = ""
    for m in history:
        role = "Utilisateur" if m["role"] == "user" else "Assistant"
        ctx += f"{role}: {m['content']}\n"
    ctx += f"Utilisateur: {content}\nAssistant:"

    response = await _ollama(ctx, model)

    with _DATA_LOCK:
        data = _load()
        if cid not in data:
            raise HTTPException(status_code=404, detail="Conversation supprimée pendant la génération.")

        now = time.time()
        data[cid]["messages"].append({"role": "user",      "content": content,  "ts": now})
        data[cid]["messages"].append({"role": "assistant", "content": response, "ts": now})
        data[cid]["updated_at"] = now

        # titre auto depuis le premier message
        if len(data[cid]["messages"]) == 2:
            data[cid]["title"] = content[:60]

        _save(data)
    return {"role": "assistant", "content": response, "model": model}
