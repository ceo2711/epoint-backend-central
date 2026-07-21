"""Serialización y avatar de sedes."""

from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.sede import Sede
from app.schemas.sede import SedeResponse
from app.services.storage.s3 import get_storage_provider
from app.utils.mime import resolve_content_type

AVATAR_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
AVATAR_MAX_BYTES = 5 * 1024 * 1024
AVATAR_EXT_BY_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def avatar_url_for(sede: Sede) -> str | None:
    key = sede.avatar_storage_key
    if not key:
        return None
    try:
        return get_storage_provider().generate_download_url(key, expires_in=3600)
    except Exception:
        return None


def serialize_sede(sede: Sede) -> SedeResponse:
    base = SedeResponse.model_validate(sede)
    return base.model_copy(update={"avatar_url": avatar_url_for(sede)})


def upload_sede_avatar(
    db: Session,
    sede: Sede,
    *,
    filename: str,
    content_type: str,
    file_bytes: bytes,
) -> SedeResponse:
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo de avatar está vacío",
        )
    if len(file_bytes) > AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El avatar no puede superar los 5 MB",
        )

    mime_type = resolve_content_type(content_type, filename)
    if mime_type not in AVATAR_ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten imágenes JPEG, PNG o WebP",
        )

    storage = get_storage_provider()
    ext = AVATAR_EXT_BY_MIME[mime_type]
    new_key = storage.build_key("sedes", str(sede.id), "avatar", f"{uuid4().hex}.{ext}")
    storage.put_object(new_key, file_bytes, mime_type)

    old_key = sede.avatar_storage_key
    sede.avatar_storage_key = new_key
    db.commit()
    db.refresh(sede)

    if old_key and old_key != new_key:
        try:
            storage.delete_object(old_key)
        except Exception:
            pass

    return serialize_sede(sede)


def delete_sede_avatar(db: Session, sede: Sede) -> SedeResponse:
    old_key = sede.avatar_storage_key
    if not old_key:
        return serialize_sede(sede)

    sede.avatar_storage_key = None
    db.commit()
    db.refresh(sede)

    try:
        get_storage_provider().delete_object(old_key)
    except Exception:
        pass

    return serialize_sede(sede)
