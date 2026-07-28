from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/branding", tags=["Branding"])

_BRANDING_DIR = Path(__file__).resolve().parents[2] / "static" / "branding"

_ASSETS: dict[str, tuple[str, str]] = {
    "logo": ("epoint-logo.png", "image/png"),
    "google-play-badge": ("google-play-badge.png", "image/png"),
    "app-store-badge": ("app-store-badge-v2.png", "image/png"),
}


@router.get("/logo")
async def brand_logo() -> FileResponse:
    """Logo público para emails y otras integraciones externas."""
    return _file_response("logo")


@router.get("/google-play-badge")
async def google_play_badge() -> FileResponse:
    """Badge de Google Play para emails."""
    return _file_response("google-play-badge")


@router.get("/app-store-badge")
async def app_store_badge() -> FileResponse:
    """Badge de App Store para emails."""
    return _file_response("app-store-badge")


def _file_response(key: str) -> FileResponse:
    filename, media_type = _ASSETS[key]
    path = _BRANDING_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Asset no encontrado: {filename}")
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        headers={"Cache-Control": "public, max-age=86400"},
    )
