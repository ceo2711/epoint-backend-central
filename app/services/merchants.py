"""Operaciones de comercios (merchants)."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.merchant import Merchant
from app.models.user import User
from app.models.user_merchant import UserMerchant


class MerchantService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def purge_merchant(self, merchant_id: int) -> None:
        """Elimina permanentemente un comercio sin clientes asociados."""
        merchant = self.db.get(Merchant, merchant_id)
        if merchant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comercio no encontrado")

        client_count = self.db.execute(
            select(func.count()).select_from(Client).where(Client.merchant_id == merchant_id)
        ).scalar_one()
        if client_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"No se puede eliminar: hay {client_count} cliente(s) asociados a este comercio",
            )

        self.db.execute(
            update(User).where(User.active_merchant_id == merchant_id).values(active_merchant_id=None)
        )
        self.db.execute(delete(UserMerchant).where(UserMerchant.merchant_id == merchant_id))
        self.db.delete(merchant)
        self.db.commit()
