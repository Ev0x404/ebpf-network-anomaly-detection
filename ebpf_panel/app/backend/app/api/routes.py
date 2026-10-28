from fastapi import APIRouter

from app.api import health, services, reports, detections, chat, bans

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(services.router, prefix="/services", tags=["services"])
router.include_router(reports.router, prefix="/reports", tags=["reports"])
router.include_router(detections.router, prefix="/detections", tags=["detections"])
router.include_router(chat.router, prefix="/chat", tags=["chat"])
router.include_router(bans.router, prefix="/bans", tags=["bans"])
