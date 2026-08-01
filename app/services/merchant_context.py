"""Contexto de comercio activo por usuario staff."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.merchant import Merchant
from app.models.user import User
from app.models.user_merchant import UserMerchant
from app.services.sede_scope import (
    ADMIN_ROLE,
    BRANCH_MANAGER_ROLE,
    CLIENT_ROLE,
)

CLIENT_ROLE_ALIAS = CLIENT_ROLE  # backwards compat if imported elsewhere


class MerchantContextService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def is_staff(self, user: User) -> bool:
        return user.role.code != CLIENT_ROLE

    def list_accessible_merchants(self, user: User) -> list[Merchant]:
        """Comercios del workspace. Son transversales a sedes (no se filtran por sede)."""
        if not self.is_staff(user):
            return []
        if user.role.code in (ADMIN_ROLE, BRANCH_MANAGER_ROLE):
            return list(
                self.db.execute(
                    select(Merchant).where(Merchant.is_active.is_(True)).order_by(Merchant.name)
                ).scalars().all()
            )
        return list(
            self.db.execute(
                select(Merchant)
                .join(UserMerchant, UserMerchant.merchant_id == Merchant.id)
                .where(UserMerchant.user_id == user.id, Merchant.is_active.is_(True))
                .order_by(Merchant.name)
            ).scalars().all()
        )

    def user_can_access_merchant(self, user: User, merchant_id: int) -> bool:
        merchant = self.db.get(Merchant, merchant_id)
        if merchant is None or not merchant.is_active:
            return False
        if user.role.code in (ADMIN_ROLE, BRANCH_MANAGER_ROLE):
            return True
        if not self.is_staff(user):
            return False
        link = self.db.execute(
            select(UserMerchant).where(
                UserMerchant.user_id == user.id,
                UserMerchant.merchant_id == merchant_id,
            )
        ).scalar_one_or_none()
        return link is not None

    def user_can_manage_merchant(self, user: User, merchant_id: int) -> bool:
        """Admin puede gestionar comercios inactivos (reactivar / purgar)."""
        merchant = self.db.get(Merchant, merchant_id)
        if merchant is None:
            return False
        if user.role.code == ADMIN_ROLE:
            return True
        return self.user_can_access_merchant(user, merchant_id)

    def set_active_merchant(self, user: User, merchant_id: int) -> Merchant:
        if not self.is_staff(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
        if not self.user_can_access_merchant(user, merchant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tenés acceso a ese comercio",
            )
        merchant = self.db.get(Merchant, merchant_id)
        assert merchant is not None
        user.active_merchant_id = merchant.id
        self.db.commit()
        self.db.refresh(user)
        return merchant

    def resolve_active_merchant_id(
        self,
        user: User,
        *,
        header_merchant_id: int | None = None,
        persist: bool = True,
    ) -> int:
        if not self.is_staff(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

        merchants = self.list_accessible_merchants(user)
        if not merchants:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No hay comercios activos asignados a tu usuario",
            )

        candidate_id = header_merchant_id or user.active_merchant_id
        if candidate_id is not None and self.user_can_access_merchant(user, candidate_id):
            if persist and user.active_merchant_id != candidate_id:
                user.active_merchant_id = candidate_id
                self.db.commit()
            return candidate_id

        if len(merchants) == 1:
            only_id = merchants[0].id
            if persist and user.active_merchant_id != only_id:
                user.active_merchant_id = only_id
                self.db.commit()
            return only_id

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seleccioná un comercio activo para continuar",
        )

    def get_active_merchant(self, user: User, merchant_id: int) -> Merchant:
        if not self.user_can_access_merchant(user, merchant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tenés acceso a ese comercio",
            )
        merchant = self.db.get(Merchant, merchant_id)
        if merchant is None or not merchant.is_active:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comercio no encontrado")
        return merchant

    def ensure_client_in_merchant(self, client_merchant_id: int | None, active_merchant_id: int) -> None:
        if client_merchant_id != active_merchant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
