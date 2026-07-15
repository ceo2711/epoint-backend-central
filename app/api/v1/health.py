from fastapi import APIRouter, Query

from app.__version__ import __version__
from app.core.config import Settings, get_settings

router = APIRouter(tags=["Salud"])


def _llm_status_summary(settings: Settings) -> dict:
    if not settings.gemini_api_key:
        return {"status": "not_configured"}
    return {"status": "configured", "model": settings.gemini_model}


@router.get("/health")
async def health_check(
    check_llm: bool = Query(
        False,
        description="Si es true, verifica conectividad con Gemini (solo fuera de development).",
    ),
) -> dict:
    settings = get_settings()
    llm_status = _llm_status_summary(settings)

    if check_llm and not settings.is_development and settings.gemini_api_key:
        from app.services.llm import get_llm_service

        llm = get_llm_service()
        if llm.is_available:
            llm_status = await llm.health_check()

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": __version__,
        "environment": settings.app_env,
        "llm": llm_status,
    }
