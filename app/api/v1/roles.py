from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.api.deps import DbSession, require_permissions
from app.models.permission import Permission, RolePermission
from app.models.role import Role
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.role import PermissionResponse, RoleCreate, RoleResponse, RoleUpdate

router = APIRouter(prefix="/roles", tags=["Roles"])


def _load_role(db: DbSession, role_id: int) -> Role | None:
    return (
        db.execute(
            select(Role)
            .options(joinedload(Role.role_permissions).joinedload(RolePermission.permission))
            .where(Role.id == role_id)
        )
        .unique()
        .scalar_one_or_none()
    )


def _role_to_response(role: Role) -> RoleResponse:
    return RoleResponse(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_active=role.is_active,
        created_at=role.created_at,
        permissions=[PermissionResponse.model_validate(rp.permission) for rp in role.role_permissions],
    )


@router.get("", response_model=list[RoleResponse])
def list_roles(
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("roles:read"))],
    include_inactive: bool = False,
) -> list[RoleResponse]:
    query = select(Role).options(
        joinedload(Role.role_permissions).joinedload(RolePermission.permission)
    )
    if not include_inactive:
        query = query.where(Role.is_active.is_(True))
    roles = db.execute(query.order_by(Role.name)).unique().scalars().all()
    return [_role_to_response(r) for r in roles]


@router.post("", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: RoleCreate,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("roles:create"))],
) -> RoleResponse:
    role = Role(
        code=payload.code.upper(),
        name=payload.name,
        description=payload.description,
    )
    db.add(role)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El código de rol ya existe")

    if payload.permission_ids:
        perms = db.execute(
            select(Permission).where(Permission.id.in_(payload.permission_ids))
        ).scalars().all()
        for perm in perms:
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    db.commit()
    role = _load_role(db, role.id)
    assert role is not None
    return _role_to_response(role)


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(
    role_id: int,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("roles:read"))],
) -> RoleResponse:
    role = _load_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rol no encontrado")
    return _role_to_response(role)


@router.patch("/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: int,
    payload: RoleUpdate,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("roles:update"))],
) -> RoleResponse:
    role = _load_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rol no encontrado")

    data = payload.model_dump(exclude_unset=True)
    permission_ids = data.pop("permission_ids", None)

    for field, value in data.items():
        setattr(role, field, value)

    if permission_ids is not None:
        role.role_permissions.clear()
        db.flush()
        perms = db.execute(
            select(Permission).where(Permission.id.in_(permission_ids))
        ).scalars().all()
        for perm in perms:
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    db.commit()
    role = _load_role(db, role_id)
    assert role is not None
    return _role_to_response(role)


@router.delete("/{role_id}", response_model=MessageResponse)
def deactivate_role(
    role_id: int,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("roles:delete"))],
) -> MessageResponse:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rol no encontrado")
    role.is_active = False
    db.commit()
    return MessageResponse(message="Rol desactivado")
