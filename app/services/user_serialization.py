"""Serialización de usuarios con URL firmada de avatar."""

from __future__ import annotations

from app.models.user import User
from app.schemas.user import UserResponse
from app.services.storage.s3 import get_storage_provider


def avatar_url_for(user: User) -> str | None:
    key = user.avatar_storage_key
    if not key:
        return None
    try:
        return get_storage_provider().generate_download_url(key, expires_in=3600)
    except Exception:
        return None


def serialize_user(user: User) -> UserResponse:
    base = UserResponse.model_validate(user)
    return base.model_copy(update={"avatar_url": avatar_url_for(user)})
