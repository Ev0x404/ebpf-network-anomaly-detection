from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from app.core.settings import settings
from app.models.schemas import ReportItem

router = APIRouter()


def _preview(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:500]
    except Exception:
        return ""


@router.get("", response_model=list[ReportItem])
def list_reports():
    reports_dir = settings.resolved_reports_dir
    if not reports_dir.exists():
        return []

    EXTS = {".txt", ".json", ".jsonl", ".log", ".md", ".html", ".csv"}
    all_files = []
    for path in reports_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in EXTS:
            all_files.append(path)

    items = []
    for path in sorted(all_files, key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        relative_name = path.relative_to(reports_dir).as_posix()
        items.append(
            ReportItem(
                name=relative_name,
                path=str(path),
                size_bytes=stat.st_size,
                modified_at=stat.st_mtime,
                preview=_preview(path),
            )
        )
    return items


@router.get("/{name:path}", response_class=PlainTextResponse)
def read_report(name):
    reports_dir = settings.resolved_reports_dir.resolve()
    path = (reports_dir / name).resolve()
    if reports_dir != path and reports_dir not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid report path")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    return path.read_text(encoding="utf-8", errors="replace")
