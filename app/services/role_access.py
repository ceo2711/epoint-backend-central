"""Helpers de roles de administración (global vs sede) y liderazgo de área."""

from __future__ import annotations

from app.models.user import User

ADMIN_ROLE = "ADMIN"
BRANCH_MANAGER_ROLE = "BRANCH_MANAGER"
AREA_LEADER_ROLE = "AREA_LEADER"
SALES_AREA_CODE = "VENTAS"


def is_global_admin(user: User) -> bool:
    """Administrador de todas las sedes."""
    return user.role.code == ADMIN_ROLE


def is_branch_manager(user: User) -> bool:
    return user.role.code == BRANCH_MANAGER_ROLE


def is_sede_admin(user: User) -> bool:
    """Admin global o gerente de sucursal (acceso completo dentro de su alcance)."""
    return user.role.code in (ADMIN_ROLE, BRANCH_MANAGER_ROLE)


def is_area_leader(user: User) -> bool:
    return user.role.code == AREA_LEADER_ROLE


def user_area_code(user: User) -> str | None:
    area = getattr(user, "area", None)
    return area.code if area is not None else None


def is_sales_area_leader(user: User) -> bool:
    """Líder de área asignado al área comercial (VENTAS)."""
    return is_area_leader(user) and user_area_code(user) == SALES_AREA_CODE


def can_supervise_sales_reps(user: User) -> bool:
    """Puede ver/filtrar el trabajo de vendedores de su alcance (sede)."""
    return is_sede_admin(user) or is_sales_area_leader(user)


def bypasses_permission(user: User, permission: str) -> bool:
    """
    ADMIN: bypass total.
    BRANCH_MANAGER: bypass total excepto gestión de sedes/merchants y borrado de clientes
    (solo ADMIN). Puede usar merchants como workspace (selector), pero no administrar el CRUD.
    """
    if is_global_admin(user):
        return True
    if is_branch_manager(user):
        if (
            permission.startswith("sedes:")
            or permission.startswith("merchants:")
            or permission.startswith("sources:")
            or permission == "clients:delete"
        ):
            return False
        return True
    return False
