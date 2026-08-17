"""Helpers de roles de administración (global vs sede) y liderazgo de área."""

from __future__ import annotations

from app.models.user import User

ADMIN_ROLE = "ADMIN"
BRANCH_MANAGER_ROLE = "BRANCH_MANAGER"
AREA_LEADER_ROLE = "AREA_LEADER"
SALES_REP_ROLE = "SALES_REP"
SUB_SELLER_ROLE = "SUB_SELLER"
ADVISOR_ROLE = "ADVISOR"
SALES_STAFF_ROLES = frozenset({SALES_REP_ROLE, SUB_SELLER_ROLE})
SALES_AREA_CODE = "VENTAS"
ONBOARDING_AREA_CODE = "ONBOARDING"
ASESORES_AREA_CODE = "ASESORES"

# Permisos extra de onboarding: líder de área, jefe de asesores y asesor.
ONBOARDING_LEADER_EXTRA_PERMISSIONS = frozenset(
    {"clients:approve", "clients:update", "credentials:read"}
)


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


def is_advisor(user: User) -> bool:
    return user.role.code == ADVISOR_ROLE


def can_manage_onboarding(user: User) -> bool:
    """Admin/gerente, líder de onboarding, jefe de asesores o asesor."""
    return (
        is_sede_admin(user)
        or is_onboarding_area_leader(user)
        or is_advisors_area_leader(user)
        or is_advisor(user)
    )


def can_supervise_sales_reps(user: User) -> bool:
    """Puede ver/filtrar el trabajo de vendedores de su alcance (sede)."""
    return is_sede_admin(user) or is_sales_area_leader(user)


def can_filter_clients_by_sales_rep(user: User) -> bool:
    """Filtro por vendedor en clientes: supervisión comercial u operadores de onboarding (no el asesor de línea)."""
    if is_advisor(user):
        return False
    return can_supervise_sales_reps(user) or can_manage_onboarding(user)


def can_run_onboarding_reminders(user: User) -> bool:
    """Recordatorios masivos: onboarding/admin, no el asesor de línea."""
    return can_manage_onboarding(user) and not is_advisor(user)


def can_upload_client_documents(user: User) -> bool:
    """Subir/reemplazar documentos: cliente, onboarding y admin/gerente. No el asesor."""
    if user.role.code == "CLIENT":
        return True
    return can_manage_onboarding(user) and not is_advisor(user)


def can_download_client_documents(user: User) -> bool:
    """Descargar documentos: cliente, admin/gerente y asesor. Onboarding solo ve/carga."""
    if user.role.code == "CLIENT":
        return True
    return is_sede_admin(user) or is_advisor(user)


def can_access_docusign(user: User) -> bool:
    """Ver/enviar contratos: comercial, admin de sede, líderes de área u operadores de onboarding."""
    if user.role.code in (
        ADMIN_ROLE,
        BRANCH_MANAGER_ROLE,
        SALES_REP_ROLE,
        SUB_SELLER_ROLE,
        AREA_LEADER_ROLE,
    ):
        return True
    return can_manage_onboarding(user)


def _has_onboarding_extra_permissions(user: User) -> bool:
    return is_onboarding_area_leader(user) or is_advisors_area_leader(user) or is_advisor(user)


def bypasses_permission(user: User, permission: str) -> bool:
    """
    ADMIN: bypass total.
    BRANCH_MANAGER: bypass total excepto catálogo solo-ADMIN (sedes, merchants,
    sources), escritura de roles y borrado de clientes. Puede usar merchants como
    workspace (selector) y leer roles para alta de usuarios, pero no administrar
    el CRUD de roles ni ver la pantalla de catálogo (nav solo ADMIN).
    Onboarding (líder, jefe de asesores, asesor): clients:approve/update y credentials:read.
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
    if _has_onboarding_extra_permissions(user) and permission in ONBOARDING_LEADER_EXTRA_PERMISSIONS:
        return True
    return False
