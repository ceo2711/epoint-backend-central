import math
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.api.deps import DbSession, require_permissions
from app.core.security import hash_password
from app.models.role import Role
from app.models.user import User
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.services.auth import AuthService
from app.services.sede_scope import (
    assert_actor_can_assign_role,
    effective_sede_id,
    is_global_admin,
    resolve_sede_for_user,
    sync_user_merchants_for_sede,
)
from app.services.user_serialization import serialize_user

router = APIRouter(prefix="/users", tags=["Usuarios"])

AREA_REQUIRED_ROLE_CODES = frozenset({"AREA_LEADER"})


def _assert_area_required(role: Role, area_id: int | None) -> None:
    if role.code in AREA_REQUIRED_ROLE_CODES and area_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El líder de área debe tener un área asignada",
        )


def _staff_users_query():
    """Usuarios internos de la plataforma (empleados), sin cuentas portal de clientes."""
    return (
        select(User)
        .options(joinedload(User.role), joinedload(User.area), joinedload(User.sede))
        .join(Role)
        .where(Role.code != "CLIENT")
    )


def _get_staff_user(db: DbSession, user_id: int) -> User | None:
    return (
        db.execute(_staff_users_query().where(User.id == user_id))
        .unique()
        .scalar_one_or_none()
    )


def _get_role(db: DbSession, role_id: int) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rol inválido")
    return role


def _assert_can_manage_target(actor: User, target: User) -> None:
    if is_global_admin(actor):
        return
    scope = effective_sede_id(actor)
    if scope is None or target.sede_id != scope:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    if target.role.code in ("ADMIN", "BRANCH_MANAGER"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")


@router.get("", response_model=PaginatedResponse[UserResponse])
def list_users(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("users:read"))],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    sede_id: int | None = None,
    is_active: bool | None = None,
) -> PaginatedResponse[UserResponse]:
    query = _staff_users_query()

    scope = effective_sede_id(current_user)
    if scope is not None:
        query = query.where(User.sede_id == scope)
    elif sede_id is not None:
        query = query.where(User.sede_id == sede_id)

    if search:
        words = [part.strip() for part in search.strip().split() if part.strip()]
        for word in words:
            term = f"%{word}%"
            full_name = func.concat(User.first_name, " ", User.last_name)
            query = query.where(
                (User.email.ilike(term))
                | (User.first_name.ilike(term))
                | (User.last_name.ilike(term))
                | full_name.ilike(term)
            )
    if is_active is not None:
        query = query.where(User.is_active == is_active)

    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    users = (
        db.execute(
            query.order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .unique()
        .scalars()
        .all()
    )

    return PaginatedResponse(
        items=[serialize_user(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("users:create"))],
) -> UserResponse:
    existing = db.execute(select(User).where(User.email == payload.email.lower())).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El email ya está registrado")

    role = _get_role(db, payload.role_id)
    assert_actor_can_assign_role(current_user, role)
    _assert_area_required(role, payload.area_id)
    sede_id = resolve_sede_for_user(
        db,
        actor=current_user,
        role=role,
        requested_sede_id=payload.sede_id,
    )

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
        role_id=payload.role_id,
        area_id=payload.area_id,
        sede_id=sede_id,
    )
    db.add(user)
    db.flush()
    sync_user_merchants_for_sede(db, user, sede_id)
    db.commit()
    db.refresh(user)
    db.refresh(user, attribute_names=["role", "area", "sede"])
    return serialize_user(user)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("users:read"))],
) -> UserResponse:
    user = _get_staff_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    _assert_can_manage_target(current_user, user)
    return serialize_user(user)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("users:update"))],
) -> UserResponse:
    user = _get_staff_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    _assert_can_manage_target(current_user, user)

    data = payload.model_dump(exclude_unset=True)
    if "email" in data and data["email"]:
        data["email"] = data["email"].lower()

    role = user.role
    if "role_id" in data and data["role_id"] is not None:
        role = _get_role(db, int(data["role_id"]))
        assert_actor_can_assign_role(current_user, role)

    next_area_id = data["area_id"] if "area_id" in data else user.area_id
    _assert_area_required(role, next_area_id)

    sede_in_payload = "sede_id" in data
    if "role_id" in data or sede_in_payload:
        requested_sede = data.pop("sede_id") if sede_in_payload else user.sede_id
        data["sede_id"] = resolve_sede_for_user(
            db,
            actor=current_user,
            role=role,
            requested_sede_id=requested_sede,
        )

    password = data.pop("password", None)
    if password:
        user.password_hash = hash_password(password)
        user.must_change_password = True

    previous_sede = user.sede_id
    for field, value in data.items():
        setattr(user, field, value)

    if user.sede_id != previous_sede or "role_id" in data:
        sync_user_merchants_for_sede(db, user, user.sede_id)

    db.commit()
    db.refresh(user)
    db.refresh(user, attribute_names=["role", "area", "sede"])
    return serialize_user(user)


@router.post("/{user_id}/avatar", response_model=UserResponse)
async def upload_user_avatar(
    user_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("users:update"))],
    file: UploadFile = File(...),
) -> UserResponse:
    user = _get_staff_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    _assert_can_manage_target(current_user, user)
    file_bytes = await file.read()
    return AuthService(db).upload_avatar(
        user,
        filename=file.filename or "avatar.jpg",
        content_type=file.content_type or "application/octet-stream",
        file_bytes=file_bytes,
    )


@router.delete("/{user_id}/avatar", response_model=UserResponse)
def delete_user_avatar(
    user_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("users:update"))],
) -> UserResponse:
    user = _get_staff_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    _assert_can_manage_target(current_user, user)
    return AuthService(db).delete_avatar(user)


@router.delete("/{user_id}", response_model=MessageResponse)
def deactivate_user(
    user_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("users:delete"))],
) -> MessageResponse:
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No podés desactivar tu propia cuenta")
    user = _get_staff_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    _assert_can_manage_target(current_user, user)
    user.is_active = False
    db.commit()
    return MessageResponse(message="Usuario desactivado")
