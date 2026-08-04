"""Helpers de roles de administración (global vs sede) y liderazgo de área."""

from __future__ import annotations

from app.models.user import User

ADMIN_ROLE = "ADMIN"
BRANCH_MANAGER_ROLE = "BRANCH_MANAGER"
AREA_LEADER_ROLE = "AREA_LEADER"
SALES_REP_ROLE = "SALES_REP"
SUB_SELLER_ROLE = "SUB_SELLER"
SALES_STAFF_ROLES = frozenset({SALES_REP_ROLE, SUB_SELLER_ROLE})
SALES_AREA_CODE = "VENTAS"
ONBOARDING_AREA_CODE = "ONBOARDING"
ASESORES_AREA_CODE = "ASESORES"

# Permisos de “encargado de onboarding” aplicados al líder de área ONBOARDING.
ONBOARDING_LEADER_EXTRA_PERMISSIONS = frozenset({"clients:approve", "credentials:read"})


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


def is_sales_staff(user: User) -> bool:
    """Vendedor o subvendedor (trabajo comercial de campo)."""
    return user.role.code in SALES_STAFF_ROLES


def is_sub_seller(user: User) -> bool:
    """Subvendedor: rol SUB_SELLER o SALES_REP legacy con padre."""
    return user.role.code == SUB_SELLER_ROLE or user.parent_user_id is not None


def is_lead_sales_rep(user: User) -> bool:
    """Vendedor titular (puede gestionar equipo si es elegible)."""
    return user.role.code == SALES_REP_ROLE and user.parent_user_id is None


def user_area_code(user: User) -> str | None:
    area = getattr(user, "area", None)
    return area.code if area is not None else None


def is_sales_area_leader(user: User) -> bool:
    """Líder de área asignado al área comercial (VENTAS)."""
    return is_area_leader(user) and user_area_code(user) == SALES_AREA_CODE


def can_sell(user: User) -> bool:
    """Puede operar herramientas comerciales propias (prospectos, Calendly, contratos, pagos)."""
    return is_sales_staff(user) or is_sales_area_leader(user)


def can_be_prospect_owner(user: User) -> bool:
    """Puede figurar como assigned_to de un prospecto."""
    return is_sales_staff(user) or is_sales_area_leader(user)


def can_own_sub_sellers(user: User) -> bool:
    """Titular potencial de 'Mi equipo' (vendedor titular o líder de ventas)."""
    return is_lead_sales_rep(user) or is_sales_area_leader(user)


def is_onboarding_area_leader(user: User) -> bool:
    """Líder de área de onboarding (antes: Encargado de Onboarding)."""
    return is_area_leader(user) and user_area_code(user) == ONBOARDING_AREA_CODE


def is_advisors_area_leader(user: User) -> bool:
    """Líder de área de asesores."""
    return is_area_leader(user) and user_area_code(user) == ASESORES_AREA_CODE


def can_manage_onboarding(user: User) -> bool:
    """Admin/gerente o líder de onboarding: aprueba clientes y gestiona onboarding."""
    return is_sede_admin(user) or is_onboarding_area_leader(user)


def can_supervise_sales_reps(user: User) -> bool:
    """Puede ver/filtrar el trabajo de vendedores de su alcance (sede)."""
    return is_sede_admin(user) or is_sales_area_leader(user)


def can_filter_clients_by_sales_rep(user: User) -> bool:
    """Filtro por vendedor en clientes: gerente/admin, líder ventas o líder onboarding."""
    return can_supervise_sales_reps(user) or is_onboarding_area_leader(user)


def bypasses_permission(user: User, permission: str) -> bool:
    """
    ADMIN: bypass total.
    BRANCH_MANAGER: bypass total excepto catálogo solo-ADMIN (sedes, merchants,
    sources), escritura de roles y borrado de clientes. Puede usar merchants como
    workspace (selector) y leer roles para alta de usuarios, pero no administrar
    el CRUD de roles ni ver la pantalla de catálogo (nav solo ADMIN).
    Líder de onboarding: clients:approve y credentials:read.
    """
    if is_global_admin(user):
        return True
    if is_branch_manager(user):
        if (
            permission.startswith("sedes:")
            or permission.startswith("merchants:")
            or permission.startswith("sources:")
            or permission in {"roles:create", "roles:update", "roles:delete"}
            or permission == "clients:delete"
        ):
            return False
        return True
    if is_onboarding_area_leader(user) and permission in ONBOARDING_LEADER_EXTRA_PERMISSIONS:
        return True
    return False
