from fastapi import APIRouter

from app.core.config import get_settings
from app.services.llm import get_llm_service

router = APIRouter(tags=["Salud"])


@router.get("/health")
async def health_check() -> dict:
    settings = get_settings()
    llm = get_llm_service()
    llm_status = await llm.health_check() if llm.is_available else {"status": "not_configured"}

    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
        "llm": llm_status,
    }
