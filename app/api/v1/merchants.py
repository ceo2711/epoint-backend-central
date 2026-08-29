from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import ActiveMerchantId, CurrentUser, DbSession, require_any_permissions, require_permissions
from app.models.merchant import Merchant
from app.models.sede import Sede
from app.models.user import User
from app.schemas.client import MerchantBrief
from app.schemas.common import MessageResponse
from app.schemas.merchant import MerchantCreate, MerchantResponse, MerchantUpdate
from app.services.merchant_context import MerchantContextService
from app.services.merchants import MerchantService

router = APIRouter(prefix="/merchants", tags=["Merchants"])


def _resolve_sede_id(db: DbSession, sede_id: int | None) -> int:
    if sede_id is not None:
        sede = db.get(Sede, sede_id)
        if sede is None or not sede.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sede inválida")
        return sede.id
    default = db.execute(select(Sede).where(Sede.is_active.is_(True)).order_by(Sede.id)).scalars().first()
    if default is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No hay sedes activas")
    return default.id


@router.get("/options", response_model=list[MerchantBrief])
def list_merchant_options(
    db: DbSession,
    current_user: Annotated[User, Depends(require_any_permissions("clients:create", "clients:update"))],
) -> list[MerchantBrief]:
    merchants = MerchantContextService(db).list_accessible_merchants(current_user)
    return [MerchantBrief.model_validate(m) for m in merchants]


@router.get("", response_model=list[MerchantResponse])
def list_merchants(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("merchants:read"))],
    include_inactive: bool = False,
) -> list[MerchantResponse]:
    # Los merchants son transversales a sedes; el alcance de sede aplica a datos, no al workspace.
    _ = current_user
    query = select(Merchant).order_by(Merchant.name)
    if not include_inactive:
        query = query.where(Merchant.is_active.is_(True))
    merchants = db.execute(query).scalars().all()
    return [MerchantResponse.model_validate(m) for m in merchants]


@router.post("", response_model=MerchantResponse, status_code=status.HTTP_201_CREATED)
def create_merchant(
    payload: MerchantCreate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("merchants:create"))],
) -> MerchantResponse:
    from app.services.sede_scope import effective_sede_id, is_branch_manager

    sede_id = _resolve_sede_id(db, payload.sede_id)
    actor_sede = effective_sede_id(current_user)
    if actor_sede is not None:
        if is_branch_manager(current_user):
            sede_id = actor_sede
        elif sede_id != actor_sede:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes crear comercios en tu sede",
            )

    merchant = Merchant(
        code=payload.code.lower().strip(),
        name=payload.name.strip(),
        description=payload.description,
        sede_id=sede_id,
    )
    db.add(merchant)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El código de merchant ya existe")
    db.refresh(merchant)
    return MerchantResponse.model_validate(merchant)


@router.get("/{merchant_id}", response_model=MerchantResponse)
def get_merchant(
    merchant_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("merchants:read"))],
) -> MerchantResponse:
    merchant = db.get(Merchant, merchant_id)
    if merchant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant no encontrado")
    if not MerchantContextService(db).user_can_manage_merchant(current_user, merchant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant no encontrado")
    return MerchantResponse.model_validate(merchant)


@router.patch("/{merchant_id}", response_model=MerchantResponse)
def update_merchant(
    merchant_id: int,
    payload: MerchantUpdate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("merchants:update"))],
) -> MerchantResponse:
    from app.services.sede_scope import is_branch_manager

    merchant = db.get(Merchant, merchant_id)
    if merchant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant no encontrado")
    if not MerchantContextService(db).user_can_manage_merchant(current_user, merchant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant no encontrado")

    data = payload.model_dump(exclude_unset=True)
    # Los merchants son transversales; el gerente no puede reasignar sede del comercio
    if is_branch_manager(current_user):
        data.pop("sede_id", None)
    for field, value in data.items():
        setattr(merchant, field, value)

    db.commit()
    db.refresh(merchant)
    return MerchantResponse.model_validate(merchant)


@router.delete("/{merchant_id}", response_model=MessageResponse)
def deactivate_merchant(
    merchant_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("merchants:delete"))],
) -> MessageResponse:
    merchant = db.get(Merchant, merchant_id)
    if merchant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant no encontrado")
    if not MerchantContextService(db).user_can_manage_merchant(current_user, merchant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant no encontrado")
    merchant.is_active = False
    db.commit()
    return MessageResponse(message="Merchant desactivado")


@router.post("/{merchant_id}/purge", response_model=MessageResponse)
def purge_merchant(
    merchant_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("merchants:delete"))],
) -> MessageResponse:
    merchant = db.get(Merchant, merchant_id)
    if merchant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant no encontrado")
    if not MerchantContextService(db).user_can_manage_merchant(current_user, merchant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant no encontrado")
    MerchantService(db).purge_merchant(merchant_id)
    return MessageResponse(message="Comercio eliminado permanentemente")
