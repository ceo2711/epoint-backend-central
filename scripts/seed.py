"""Carga datos iniciales: roles, permisos, áreas y usuario administrador."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password

from app.models.area import Area
from app.models.board import BoardTemplate, BoardTemplateCard, BoardTemplateList
from app.models.merchant import Merchant
from app.models.permission import Permission, RolePermission
from app.models.role import Role
from app.models.sede import Sede
from app.models.user import User
from app.services.sede_scope import SEDE_SCOPED_ROLES, sync_user_merchants_for_sede
from app.services.sources import ensure_default_sources
from app.constants.default_board_cards import EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL, default_cards_for_column
from app.constants.kanban_columns import KANBAN_COLUMN_TITLES

PERMISSIONS = [
    ("users:read", "Ver usuarios"),
    ("users:create", "Crear usuarios"),
    ("users:update", "Editar usuarios"),
    ("users:delete", "Desactivar usuarios"),
    ("areas:read", "Ver áreas"),
    ("areas:create", "Crear áreas"),
    ("areas:update", "Editar áreas"),
    ("areas:delete", "Desactivar áreas"),
    ("roles:read", "Ver roles"),
    ("roles:create", "Crear roles"),
    ("roles:update", "Editar roles"),
    ("roles:delete", "Desactivar roles"),
    ("clients:read", "Ver clientes"),
    ("clients:create", "Registrar clientes"),
    ("clients:update", "Editar clientes"),
    ("clients:approve", "Aprobar/rechazar clientes"),
    ("clients:delete", "Eliminar clientes"),
    ("prospects:read", "Ver prospectos"),
    ("prospects:create", "Registrar prospectos"),
    ("prospects:update", "Gestionar prospectos"),
    ("documents:read", "Ver documentos"),
    ("documents:upload", "Subir documentos"),
    ("boards:read", "Ver tableros"),
    ("boards:manage", "Gestionar tableros"),
    ("credentials:read", "Ver credenciales cifradas"),
    ("merchants:read", "Ver merchants"),
    ("merchants:create", "Crear merchants"),
    ("merchants:update", "Editar merchants"),
    ("merchants:delete", "Desactivar merchants"),
    ("sources:read", "Ver sources"),
    ("sources:create", "Crear sources"),
    ("sources:update", "Editar sources"),
    ("sources:delete", "Desactivar sources"),
    ("sedes:read", "Ver sedes"),
    ("sedes:create", "Crear sedes"),
    ("sedes:update", "Editar sedes"),
    ("sedes:delete", "Desactivar sedes"),
    ("calendly:read", "Ver calendario de reuniones"),
    ("calendly:manage", "Conectar y sincronizar Calendly"),
    ("payments:read", "Ver links de pago"),
    ("payments:create", "Crear links de pago"),
    ("payments:manage", "Configurar proveedores de pago"),
]

ROLES = {
    "ADMIN": {
        "name": "Administrador",
        "description": "Acceso total al sistema y a todas las sedes",
        "permissions": "*",
    },
    "AREA_LEADER": {
        "name": "Líder de área",
        "description": "Supervisa el trabajo de su área",
        "permissions": [
            "users:read",
            "clients:read",
            "clients:create",
            "clients:update",
            "prospects:read",
            "prospects:create",
            "prospects:update",
            "documents:read",
            "documents:upload",
            "boards:read",
            "boards:manage",
            "calendly:read",
            "calendly:manage",
            "payments:read",
            "payments:create",
        ],
    },
    "BRANCH_MANAGER": {
        "name": "Gerente de sucursal",
        "description": "Acceso completo al portal limitado a su sede (equivalente al admin de una sucursal)",
        "permissions": "*",
    },
    "SALES_REP": {
        "name": "Vendedor",
        "description": "Registra clientes nuevos",
        "permissions": ["clients:read", "clients:create", "clients:update", "prospects:read", "prospects:create", "prospects:update", "calendly:read", "calendly:manage", "payments:read", "payments:create"],
    },
    "SUB_SELLER": {
        "name": "Subvendedor",
        "description": "Vendedor bajo la supervisión de un vendedor titular",
        "permissions": [
            "clients:read",
            "clients:create",
            "clients:update",
            "prospects:read",
            "prospects:create",
            "prospects:update",
            "calendly:read",
            "calendly:manage",
            "payments:read",
            "payments:create",
        ],
    },
    "ADVISOR": {
        "name": "Asesor",
        "description": "Acompaña clientes asignados",
        "permissions": [
            "clients:read",
            "documents:read",
            "documents:upload",
            "boards:read",
            "boards:manage",
            "credentials:read",
        ],
    },
    "CLIENT": {
        "name": "Cliente",
        "description": "Portal del cliente",
        "permissions": ["documents:upload", "boards:read"],
    },
}

AREAS = [
    ("VENTAS", "Ventas", "Equipo comercial"),
    ("ONBOARDING", "Onboarding", "Equipo de incorporación de clientes"),
    ("ASESORES", "Asesores", "Equipo de acompañamiento de clientes"),
]

MERCHANTS = [
    ("epoint-lab", "ePoint Lab", "Laboratorio y servicios técnicos"),
    ("epoint-solution", "ePoint Solution", "Soluciones empresariales"),
    ("epoint-credits", "ePoint Credits", "Créditos y financiamiento"),
]

ADMIN_EMAIL = "admin@epoint.com"
ADMIN_PASSWORD = "Admin123!"

DEMO_USERS = [
    ("vendedor@epoint.com", "Vendedor", "Demo", "SALES_REP", "VENTAS", "Vendedor123!"),
    ("lider.ventas@epoint.com", "Líder", "Ventas", "AREA_LEADER", "VENTAS", "LiderVentas123!"),
    ("onboarding@epoint.com", "Líder", "Onboarding", "AREA_LEADER", "ONBOARDING", "Onboard123!"),
    ("asesor@epoint.com", "Asesor", "Demo", "ADVISOR", "ASESORES", "Asesor123!"),
    ("gerente@epoint.com", "Gerente", "Sucursal", "BRANCH_MANAGER", "VENTAS", "Gerente123!"),
    # Autor técnico de comentarios default del tablero (no es líder de área).
    (EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL, "EPoint", "Corp", "ADVISOR", "ASESORES", "SystemBoard123!"),
]

BOARD_TEMPLATE = {
    "code": "DEFAULT_ONBOARDING",
    "name": "Onboarding estándar",
    "lists": [
        {
            "title": title,
            "position": index,
            "cards": [
                {
                    "title": card.title,
                    "description_md": card.description_md,
                    "position": card.position,
                    "requires_credentials": card.requires_credentials,
                    "requires_file_upload": card.requires_file_upload,
                }
                for card in default_cards_for_column(title)
            ],
        }
        for index, title in enumerate(KANBAN_COLUMN_TITLES)
    ],
}


def seed() -> None:
    db = SessionLocal()
    try:
        # Permisos
        perm_map: dict[str, Permission] = {}
        for code, name in PERMISSIONS:
            perm = db.execute(select(Permission).where(Permission.code == code)).scalar_one_or_none()
            if perm is None:
                perm = Permission(code=code, name=name)
                db.add(perm)
            perm_map[code] = perm
        db.flush()

        all_perm_ids = [p.id for p in perm_map.values()]

        # Roles
        for code, data in ROLES.items():
            role = db.execute(select(Role).where(Role.code == code)).scalar_one_or_none()
            if role is None:
                role = Role(code=code, name=data["name"], description=data["description"])
                db.add(role)
                db.flush()

            existing_rp = {
                rp.permission_id
                for rp in db.execute(
                    select(RolePermission).where(RolePermission.role_id == role.id)
                ).scalars().all()
            }
            target_perms = all_perm_ids if data["permissions"] == "*" else [
                perm_map[p].id for p in data["permissions"]
            ]
            for pid in target_perms:
                if pid not in existing_rp:
                    db.add(RolePermission(role_id=role.id, permission_id=pid))

        db.flush()

        # Sedes, merchants y borrado de clientes: solo ADMIN
        # (el gerente usa merchants como workspace, sin CRUD; no puede eliminar clientes).
        admin_only_catalog = {
            perm_map[code].id
            for code in (
                "sedes:read",
                "sedes:create",
                "sedes:update",
                "sedes:delete",
                "merchants:read",
                "merchants:create",
                "merchants:update",
                "merchants:delete",
                "sources:read",
                "sources:create",
                "sources:update",
                "sources:delete",
                "roles:create",
                "roles:update",
                "roles:delete",
                "clients:delete",
            )
            if code in perm_map
        }
        for role in db.execute(select(Role).where(Role.code != "ADMIN")).scalars().all():
            for rp in db.execute(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id.in_(admin_only_catalog),
                )
            ).scalars().all():
                db.delete(rp)

        # Áreas
        for code, name, desc in AREAS:
            area = db.execute(select(Area).where(Area.code == code)).scalar_one_or_none()
            if area is None:
                db.add(Area(code=code, name=name, description=desc))

        ensure_default_sources(db)

        # Sede principal
        sede = db.execute(select(Sede).where(Sede.code == "sede-principal")).scalar_one_or_none()
        if sede is None:
            sede = Sede(
                code="sede-principal",
                name="Sede Principal",
                description="Sede inicial del grupo Epoint",
            )
            db.add(sede)
            db.flush()

        # Merchants
        for code, name, desc in MERCHANTS:
            merchant = db.execute(select(Merchant).where(Merchant.code == code)).scalar_one_or_none()
            if merchant is None:
                db.add(Merchant(code=code, name=name, description=desc, sede_id=sede.id))
            elif merchant.sede_id is None:
                merchant.sede_id = sede.id

        db.flush()

        # Admin
        admin_role = db.execute(select(Role).where(Role.code == "ADMIN")).scalar_one()
        admin = db.execute(select(User).where(User.email == ADMIN_EMAIL)).scalar_one_or_none()
        if admin is None:
            db.add(
                User(
                    email=ADMIN_EMAIL,
                    password_hash=hash_password(ADMIN_PASSWORD),
                    first_name="Administrador",
                    last_name="ePoint",
                    role_id=admin_role.id,
                    is_active=True,
                )
            )

        # Usuarios demo
        area_map = {a.code: a for a in db.execute(select(Area)).scalars().all()}
        role_map = {r.code: r for r in db.execute(select(Role)).scalars().all()}
        for email, fname, lname, role_code, area_code, pwd in DEMO_USERS:
            demo = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if demo is None:
                demo = User(
                    email=email,
                    password_hash=hash_password(pwd),
                    first_name=fname,
                    last_name=lname,
                    role_id=role_map[role_code].id,
                    area_id=area_map.get(area_code).id if area_code in area_map else None,
                    sede_id=sede.id if role_code in SEDE_SCOPED_ROLES else None,
                    is_active=True,
                )
                db.add(demo)
                db.flush()
            else:
                # Mantener demos alineados al modelo actual (roles/áreas).
                if role_code in role_map:
                    demo.role_id = role_map[role_code].id
                if area_code in area_map:
                    demo.area_id = area_map[area_code].id
                if demo.sede_id is None and role_code in SEDE_SCOPED_ROLES:
                    demo.sede_id = sede.id
                demo.is_active = True
            if demo is not None and demo.sede_id is not None:
                sync_user_merchants_for_sede(db, demo, demo.sede_id)

        # Rol legacy: no asignable
        legacy_om = db.execute(select(Role).where(Role.code == "ONBOARDING_MANAGER")).scalar_one_or_none()
        if legacy_om is not None:
            legacy_om.is_active = False
            legacy_om.name = "Encargado de Onboarding (deprecado)"
            legacy_om.description = "Reemplazado por Líder de área + área Onboarding"

        # Staff operativo sin sede: backfill a sede principal
        for user in db.execute(
            select(User).join(Role).where(Role.code.in_(tuple(SEDE_SCOPED_ROLES)), User.sede_id.is_(None))
        ).scalars().all():
            user.sede_id = sede.id
            sync_user_merchants_for_sede(db, user, sede.id)

        # Template de tablero
        tpl = db.execute(
            select(BoardTemplate).where(BoardTemplate.code == BOARD_TEMPLATE["code"])
        ).scalar_one_or_none()
        if tpl is None:
            tpl = BoardTemplate(code=BOARD_TEMPLATE["code"], name=BOARD_TEMPLATE["name"])
            db.add(tpl)
            db.flush()
            for list_data in BOARD_TEMPLATE["lists"]:
                bl = BoardTemplateList(
                    template_id=tpl.id,
                    title=list_data["title"],
                    position=list_data["position"],
                )
                db.add(bl)
                db.flush()
                for card_data in list_data["cards"]:
                    db.add(
                        BoardTemplateCard(
                            template_list_id=bl.id,
                            title=card_data["title"],
                            instructions_md=card_data.get("instructions_md"),
                            external_links=card_data.get("external_links"),
                            position=card_data["position"],
                            requires_credentials=card_data.get("requires_credentials", False),
                            requires_file_upload=card_data.get("requires_file_upload", False),
                        )
                    )

        db.commit()
        print("Seed completado.")
        print(f"  Admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        for email, _, _, _, _, pwd in DEMO_USERS:
            print(f"  Demo: {email} / {pwd}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
