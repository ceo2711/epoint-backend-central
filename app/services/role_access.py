"""Helpers de roles de administración (global vs sede)."""

from __future__ import annotations

from app.models.user import User

ADMIN_ROLE = "ADMIN"
BRANCH_MANAGER_ROLE = "BRANCH_MANAGER"


def is_global_admin(user: User) -> bool:
    """Administrador de todas las sedes."""
    return user.role.code == ADMIN_ROLE


def is_branch_manager(user: User) -> bool:
    return user.role.code == BRANCH_MANAGER_ROLE


def is_sede_admin(user: User) -> bool:
    """Admin global o gerente de sucursal (acceso completo dentro de su alcance)."""
    return user.role.code in (ADMIN_ROLE, BRANCH_MANAGER_ROLE)


def bypasses_permission(user: User, permission: str) -> bool:
    """
    ADMIN: bypass total.
    BRANCH_MANAGER: bypass total excepto gestión de sedes y merchants (solo ADMIN).
    Puede usar merchants como workspace (selector), pero no administrar el CRUD.
    """
    if is_global_admin(user):
        return True
    if is_branch_manager(user):
        if permission.startswith("sedes:") or permission.startswith("merchants:"):
            return False
        return True
    return False
