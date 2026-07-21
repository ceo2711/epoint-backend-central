"""Alcance por sede: aislamiento de datos entre sucursales."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.merchant import Merchant
from app.models.role import Role
from app.models.sede import Sede
from app.models.user import User
from app.models.user_merchant import UserMerchant
from app.services.role_access import (
    ADMIN_ROLE,
    BRANCH_MANAGER_ROLE,
    is_branch_manager,
    is_global_admin,
)

CLIENT_ROLE = "CLIENT"

# Roles operativos: deben tener sede y solo ven datos de esa sede
SEDE_SCOPED_ROLES = frozenset(
    {
        "SALES_REP",
        "ONBOARDING_MANAGER",
        "ADVISOR",
        "BRANCH_MANAGER",
        "AREA_LEADER",
    }
)

# Roles que el gerente de sucursal puede asignar al crear/editar usuarios
BRANCH_MANAGER_ASSIGNABLE_ROLES = frozenset(
    {
        "SALES_REP",
        "ONBOARDING_MANAGER",
        "ADVISOR",
        "AREA_LEADER",
    }
)


def is_sede_scoped(user: User) -> bool:
    return user.role.code in SEDE_SCOPED_ROLES


def role_requires_sede(role_code: str) -> bool:
    return role_code in SEDE_SCOPED_ROLES


def effective_sede_id(user: User) -> int | None:
    """None = ve todas las sedes (solo ADMIN). Resto: su sede o sin acceso."""
    if is_global_admin(user):
        return None
    return user.sede_id


def assert_sede_access(user: User, sede_id: int | None) -> None:
    """404-style isolation if the resource sede is outside the user's scope."""
    scope = effective_sede_id(user)
    if scope is None:
        return
    if sede_id is None or sede_id != scope:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recurso no encontrado")


def resolve_sede_for_user(
    db: Session,
    *,
    actor: User,
    role: Role,
    requested_sede_id: int | None,
) -> int | None:
    """Resuelve sede al crear/editar un usuario staff."""
    if not role_requires_sede(role.code):
        return None

    if is_branch_manager(actor):
        if actor.sede_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tu usuario no tiene sede asignada",
            )
        if requested_sede_id is not None and requested_sede_id != actor.sede_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo podés asignar usuarios a tu sede",
            )
        return actor.sede_id

    if requested_sede_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La sede es obligatoria para este rol",
        )

    sede = db.get(Sede, requested_sede_id)
    if sede is None or not sede.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sede inválida")
    return sede.id


def assert_actor_can_assign_role(actor: User, role: Role) -> None:
    if role.code == CLIENT_ROLE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Los clientes del portal no se gestionan desde usuarios de la plataforma",
        )
    if is_global_admin(actor):
        return
    if is_branch_manager(actor):
        if role.code not in BRANCH_MANAGER_ASSIGNABLE_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No podés asignar ese rol",
            )
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")


def sync_user_merchants_for_sede(db: Session, user: User, sede_id: int | None) -> None:
    """Asigna al usuario todos los merchants activos (son transversales a sedes)."""
    existing = list(
        db.execute(select(UserMerchant).where(UserMerchant.user_id == user.id)).scalars().all()
    )
    for link in existing:
        db.delete(link)

    if sede_id is None and user.role.code != ADMIN_ROLE:
        # Sin sede operativa: no hay workspace staff (salvo admin, que no usa user_merchants)
        user.active_merchant_id = None
        return

    merchants = list(
        db.execute(
            select(Merchant).where(Merchant.is_active.is_(True)).order_by(Merchant.name)
        ).scalars().all()
    )
    for merchant in merchants:
        db.add(UserMerchant(user_id=user.id, merchant_id=merchant.id))

    if user.active_merchant_id is not None and not any(
        m.id == user.active_merchant_id for m in merchants
    ):
        user.active_merchant_id = merchants[0].id if merchants else None
    elif user.active_merchant_id is None and merchants:
        user.active_merchant_id = merchants[0].id
