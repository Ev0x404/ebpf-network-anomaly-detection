import json
import subprocess
import time
from pathlib import Path
from fastapi import APIRouter, HTTPException
from app.core.settings import settings
from app.models.schemas import TestCatalogItem, TestRunRequest, TestRunResponse

router = APIRouter()

TESTS = [
    TestCatalogItem(
        id="nmap_connect_scan",
        name="Nmap TCP Connect Scan",
        description="Lance un scan connect TCP simple contre une cible définie dans le script.",
        command="nmap -sT 127.0.0.1",
    ),
    TestCatalogItem(
        id="nmap_syn_scan",
        name="Nmap SYN Scan",
        description="Lance un scan SYN si l'utilisateur dispose des privilèges nécessaires.",
        command="sudo nmap -sS 127.0.0.1",
    ),
]

HISTORY_FILE = Path(__file__).resolve().parent.parent.parent / "test_history.jsonl"


@router.get("/catalog", response_model=list[TestCatalogItem])
def get_catalog():
    return TESTS


@router.get("/history")
def get_history():
    if not HISTORY_FILE.exists():
        return []
    rows = []
    for line in HISTORY_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows[-100:]


@router.post("/run", response_model=TestRunResponse)
def run_test(request: TestRunRequest):
    mapping = {item.id: item for item in TESTS}
    if request.test_id not in mapping:
        raise HTTPException(status_code=404, detail="Unknown test id")

    item = mapping[request.test_id]
    try:
        result = subprocess.run(
            ["bash", "-lc", item.command],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Test execution failed: {exc}")

    payload = {
        "timestamp": time.time(),
        "test_id": item.id,
        "name": item.name,
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    return TestRunResponse(
        success=result.returncode == 0,
        stdout=result.stdout,
        stderr=result.stderr,
        return_code=result.returncode,
    )
