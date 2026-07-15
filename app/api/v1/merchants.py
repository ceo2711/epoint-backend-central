from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import ActiveMerchantId, CurrentUser, DbSession, require_any_permissions, require_permissions
from app.models.merchant import Merchant
from app.models.user import User
from app.schemas.client import MerchantBrief
from app.schemas.common import MessageResponse
from app.schemas.merchant import MerchantCreate, MerchantResponse, MerchantUpdate
from app.services.merchant_context import MerchantContextService
from app.services.merchants import MerchantService

router = APIRouter(prefix="/merchants", tags=["Merchants"])


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
    _current_user: Annotated[User, Depends(require_permissions("merchants:read"))],
    include_inactive: bool = False,
) -> list[MerchantResponse]:
    query = select(Merchant).order_by(Merchant.name)
    if not include_inactive:
        query = query.where(Merchant.is_active.is_(True))
    merchants = db.execute(query).scalars().all()
    return [MerchantResponse.model_validate(m) for m in merchants]


@router.post("", response_model=MerchantResponse, status_code=status.HTTP_201_CREATED)
def create_merchant(
    payload: MerchantCreate,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("merchants:create"))],
) -> MerchantResponse:
    merchant = Merchant(
        code=payload.code.lower().strip(),
        name=payload.name.strip(),
        description=payload.description,
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
    _current_user: Annotated[User, Depends(require_permissions("merchants:read"))],
) -> MerchantResponse:
    merchant = db.get(Merchant, merchant_id)
    if merchant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant no encontrado")
    return MerchantResponse.model_validate(merchant)


@router.patch("/{merchant_id}", response_model=MerchantResponse)
def update_merchant(
    merchant_id: int,
    payload: MerchantUpdate,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("merchants:update"))],
) -> MerchantResponse:
    merchant = db.get(Merchant, merchant_id)
    if merchant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant no encontrado")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(merchant, field, value)

    db.commit()
    db.refresh(merchant)
    return MerchantResponse.model_validate(merchant)


@router.delete("/{merchant_id}", response_model=MessageResponse)
def deactivate_merchant(
    merchant_id: int,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("merchants:delete"))],
) -> MessageResponse:
    merchant = db.get(Merchant, merchant_id)
    if merchant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant no encontrado")
    merchant.is_active = False
    db.commit()
    return MessageResponse(message="Merchant desactivado")


@router.post("/{merchant_id}/purge", response_model=MessageResponse)
def purge_merchant(
    merchant_id: int,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("merchants:delete"))],
) -> MessageResponse:
    MerchantService(db).purge_merchant(merchant_id)
    return MessageResponse(message="Comercio eliminado permanentemente")
