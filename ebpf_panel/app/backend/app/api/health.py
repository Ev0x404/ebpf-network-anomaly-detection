from fastapi import APIRouter
from app.core.settings import settings

router = APIRouter()


@router.get("/health")
def get_health():
    return {
        "status": "ok",
        "project_root": str(settings.project_root),
        "reports_dir": str(settings.resolved_reports_dir),
        "logs_dir": str(settings.resolved_logs_dir),
    }
