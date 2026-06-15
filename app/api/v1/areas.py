from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, require_permissions
from app.models.area import Area
from app.models.user import User
from app.schemas.area import AreaCreate, AreaResponse, AreaUpdate
from app.schemas.common import MessageResponse

router = APIRouter(prefix="/areas", tags=["Áreas"])


@router.get("", response_model=list[AreaResponse])
def list_areas(
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("areas:read"))],
    include_inactive: bool = False,
) -> list[AreaResponse]:
    query = select(Area).order_by(Area.name)
    if not include_inactive:
        query = query.where(Area.is_active.is_(True))
    areas = db.execute(query).scalars().all()
    return [AreaResponse.model_validate(a) for a in areas]


@router.post("", response_model=AreaResponse, status_code=status.HTTP_201_CREATED)
def create_area(
    payload: AreaCreate,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("areas:create"))],
) -> AreaResponse:
    area = Area(code=payload.code.upper(), name=payload.name, description=payload.description)
    db.add(area)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El código de área ya existe")
    db.refresh(area)
    return AreaResponse.model_validate(area)


@router.get("/{area_id}", response_model=AreaResponse)
def get_area(
    area_id: int,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("areas:read"))],
) -> AreaResponse:
    area = db.get(Area, area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Área no encontrada")
    return AreaResponse.model_validate(area)


@router.patch("/{area_id}", response_model=AreaResponse)
def update_area(
    area_id: int,
    payload: AreaUpdate,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("areas:update"))],
) -> AreaResponse:
    area = db.get(Area, area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Área no encontrada")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(area, field, value)

    db.commit()
    db.refresh(area)
    return AreaResponse.model_validate(area)


@router.delete("/{area_id}", response_model=MessageResponse)
def deactivate_area(
    area_id: int,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("areas:delete"))],
) -> MessageResponse:
    area = db.get(Area, area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Área no encontrada")
    area.is_active = False
    db.commit()
    return MessageResponse(message="Área desactivada")
