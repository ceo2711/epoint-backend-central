from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, require_any_permissions, require_permissions
from app.models.source import Source
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.source import SourceBrief, SourceCreate, SourceResponse, SourceUpdate
from app.services.sources import list_sources

router = APIRouter(prefix="/sources", tags=["Sources"])


@router.get("/options", response_model=list[SourceBrief])
def list_source_options(
    db: DbSession,
    _current_user: Annotated[
        User,
        Depends(
            require_any_permissions(
                "prospects:create",
                "prospects:update",
                "clients:create",
                "clients:update",
                "sources:read",
            )
        ),
    ],
) -> list[SourceBrief]:
    return [SourceBrief.model_validate(s) for s in list_sources(db, include_inactive=False)]


@router.get("", response_model=list[SourceResponse])
def list_all_sources(
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("sources:read"))],
    include_inactive: bool = False,
) -> list[SourceResponse]:
    return [
        SourceResponse.model_validate(s)
        for s in list_sources(db, include_inactive=include_inactive)
    ]


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
def create_source(
    payload: SourceCreate,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("sources:create"))],
) -> SourceResponse:
    source = Source(
        code=payload.code.strip().upper(),
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        sort_order=payload.sort_order,
    )
    db.add(source)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El código de source ya existe")
    db.refresh(source)
    return SourceResponse.model_validate(source)


@router.get("/{source_id}", response_model=SourceResponse)
def get_source(
    source_id: int,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("sources:read"))],
) -> SourceResponse:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source no encontrado")
    return SourceResponse.model_validate(source)


@router.patch("/{source_id}", response_model=SourceResponse)
def update_source(
    source_id: int,
    payload: SourceUpdate,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("sources:update"))],
) -> SourceResponse:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source no encontrado")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
    if "description" in data and isinstance(data["description"], str):
        data["description"] = data["description"].strip() or None
    for field, value in data.items():
        setattr(source, field, value)

    db.commit()
    db.refresh(source)
    return SourceResponse.model_validate(source)


@router.delete("/{source_id}", response_model=MessageResponse)
def deactivate_source(
    source_id: int,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("sources:delete"))],
) -> MessageResponse:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source no encontrado")
    source.is_active = False
    db.commit()
    return MessageResponse(message="Source desactivado")
