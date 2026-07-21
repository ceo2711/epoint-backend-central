from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, require_permissions
from app.models.sede import Sede
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.sede import SedeCreate, SedeResponse, SedeUpdate
from app.services.sede_serialization import delete_sede_avatar, serialize_sede, upload_sede_avatar

router = APIRouter(prefix="/sedes", tags=["Sedes"])


@router.get("", response_model=list[SedeResponse])
def list_sedes(
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("sedes:read"))],
    include_inactive: bool = False,
) -> list[SedeResponse]:
    query = select(Sede).order_by(Sede.name)
    if not include_inactive:
        query = query.where(Sede.is_active.is_(True))
    sedes = db.execute(query).scalars().all()
    return [serialize_sede(s) for s in sedes]


@router.post("", response_model=SedeResponse, status_code=status.HTTP_201_CREATED)
def create_sede(
    payload: SedeCreate,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("sedes:create"))],
) -> SedeResponse:
    sede = Sede(
        code=payload.code.lower().strip(),
        name=payload.name.strip(),
        description=payload.description,
    )
    db.add(sede)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El código de sede ya existe")
    db.refresh(sede)
    return serialize_sede(sede)


@router.get("/{sede_id}", response_model=SedeResponse)
def get_sede(
    sede_id: int,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("sedes:read"))],
) -> SedeResponse:
    sede = db.get(Sede, sede_id)
    if sede is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sede no encontrada")
    return serialize_sede(sede)


@router.patch("/{sede_id}", response_model=SedeResponse)
def update_sede(
    sede_id: int,
    payload: SedeUpdate,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("sedes:update"))],
) -> SedeResponse:
    sede = db.get(Sede, sede_id)
    if sede is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sede no encontrada")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(sede, field, value)

    db.commit()
    db.refresh(sede)
    return serialize_sede(sede)


@router.post("/{sede_id}/avatar", response_model=SedeResponse)
async def upload_avatar(
    sede_id: int,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("sedes:update"))],
    file: UploadFile = File(...),
) -> SedeResponse:
    sede = db.get(Sede, sede_id)
    if sede is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sede no encontrada")
    file_bytes = await file.read()
    return upload_sede_avatar(
        db,
        sede,
        filename=file.filename or "avatar.jpg",
        content_type=file.content_type or "application/octet-stream",
        file_bytes=file_bytes,
    )


@router.delete("/{sede_id}/avatar", response_model=SedeResponse)
def remove_avatar(
    sede_id: int,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("sedes:update"))],
) -> SedeResponse:
    sede = db.get(Sede, sede_id)
    if sede is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sede no encontrada")
    return delete_sede_avatar(db, sede)


@router.delete("/{sede_id}", response_model=MessageResponse)
def deactivate_sede(
    sede_id: int,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("sedes:delete"))],
) -> MessageResponse:
    sede = db.get(Sede, sede_id)
    if sede is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sede no encontrada")
    sede.is_active = False
    db.commit()
    return MessageResponse(message="Sede desactivada")
