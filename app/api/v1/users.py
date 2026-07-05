import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.api.deps import DbSession, require_permissions
from app.core.security import hash_password
from app.models.role import Role
from app.models.user import User
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.user import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["Usuarios"])


def _staff_users_query():
    """Usuarios internos de la plataforma (empleados), sin cuentas portal de clientes."""
    return (
        select(User)
        .options(joinedload(User.role), joinedload(User.area))
        .join(Role)
        .where(Role.code != "CLIENT")
    )


def _get_staff_user(db: DbSession, user_id: int) -> User | None:
    return (
        db.execute(_staff_users_query().where(User.id == user_id))
        .unique()
        .scalar_one_or_none()
    )


def _assert_staff_role(db: DbSession, role_id: int) -> None:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rol inválido")
    if role.code == "CLIENT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Los clientes del portal no se gestionan desde usuarios de la plataforma",
        )


@router.get("", response_model=PaginatedResponse[UserResponse])
def list_users(
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("users:read"))],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    is_active: bool | None = None,
) -> PaginatedResponse[UserResponse]:
    query = _staff_users_query()

    if search:
        term = f"%{search}%"
        query = query.where(
            (User.email.ilike(term))
            | (User.first_name.ilike(term))
            | (User.last_name.ilike(term))
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
        items=[UserResponse.model_validate(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("users:create"))],
) -> UserResponse:
    existing = db.execute(select(User).where(User.email == payload.email.lower())).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El email ya está registrado")

    _assert_staff_role(db, payload.role_id)

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
        role_id=payload.role_id,
        area_id=payload.area_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.refresh(user, attribute_names=["role", "area"])
    return UserResponse.model_validate(user)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("users:read"))],
) -> UserResponse:
    user = _get_staff_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: DbSession,
    _current_user: Annotated[User, Depends(require_permissions("users:update"))],
) -> UserResponse:
    user = _get_staff_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    data = payload.model_dump(exclude_unset=True)
    if "email" in data and data["email"]:
        data["email"] = data["email"].lower()
    if "role_id" in data and data["role_id"] is not None:
        _assert_staff_role(db, int(data["role_id"]))

    password = data.pop("password", None)
    if password:
        user.password_hash = hash_password(password)
        user.must_change_password = True

    for field, value in data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)


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
    user.is_active = False
    db.commit()
    return MessageResponse(message="Usuario desactivado")
