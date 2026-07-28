from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(prefix="/branding", tags=["Branding"])

_LOGO_PATH = Path(__file__).resolve().parents[2] / "static" / "branding" / "epoint-logo.png"


@router.get("/logo")
async def brand_logo() -> FileResponse:
    """Logo público para emails y otras integraciones externas."""
    return FileResponse(
        _LOGO_PATH,
        media_type="image/png",
        filename="epoint-logo.png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
