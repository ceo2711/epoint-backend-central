from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import safe_decode_token
from app.models.permission import Permission, RolePermission
from app.models.user import User
from app.services.merchant_context import MerchantContextService

security_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)],
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")

    payload = safe_decode_token(credentials.credentials)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    user = (
        db.execute(
            select(User)
            .options(joinedload(User.role), joinedload(User.area), joinedload(User.sede))
            .where(User.id == int(user_id))
        )
        .unique()
        .scalar_one_or_none()
    )

    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado o inactivo")

    return user


def get_user_permissions(db: Session, user: User) -> list[str]:
    from app.services.role_access import (
        ONBOARDING_LEADER_EXTRA_PERMISSIONS,
        is_onboarding_area_leader,
    )

    rows = db.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == user.role_id)
    ).all()
    perms = {row[0] for row in rows}
    if is_onboarding_area_leader(user):
        perms |= ONBOARDING_LEADER_EXTRA_PERMISSIONS
    return sorted(perms)


def require_any_permissions(*required: str):
    def checker(
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        from app.services.role_access import bypasses_permission

        if any(bypasses_permission(current_user, perm) for perm in required):
            return current_user
        user_perms = set(get_user_permissions(db, current_user))
        if not any(perm in user_perms for perm in required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para esta acción",
            )
        return current_user

    return checker


def require_permissions(*required: str):
    def checker(
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        from app.services.role_access import bypasses_permission

        if all(bypasses_permission(current_user, perm) for perm in required):
            return current_user
        user_perms = set(get_user_permissions(db, current_user))
        if not all(perm in user_perms for perm in required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para esta acción",
            )
        return current_user

    return checker


def get_active_merchant_id(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    x_merchant_id: Annotated[int | None, Header(alias="X-Merchant-Id")] = None,
) -> int:
    """Comercio activo del usuario staff (header o preferencia guardada)."""
    if current_user.role.code == "CLIENT":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Los clientes del portal no usan contexto de comercio",
        )
    return MerchantContextService(db).resolve_active_merchant_id(
        current_user,
        header_merchant_id=x_merchant_id,
    )


ActiveMerchantId = Annotated[int, Depends(get_active_merchant_id)]


def get_optional_active_merchant_id(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    x_merchant_id: Annotated[int | None, Header(alias="X-Merchant-Id")] = None,
) -> int | None:
    """Comercio activo para staff; None para clientes del portal."""
    if current_user.role.code == "CLIENT":
        return None
    return MerchantContextService(db).resolve_active_merchant_id(
        current_user,
        header_merchant_id=x_merchant_id,
    )


OptionalActiveMerchantId = Annotated[int | None, Depends(get_optional_active_merchant_id)]


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]
