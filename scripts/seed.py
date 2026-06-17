"""Carga datos iniciales: roles, permisos, áreas y usuario administrador."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password

from app.models.area import Area
from app.models.board import BoardTemplate, BoardTemplateCard, BoardTemplateList
from app.models.permission import Permission, RolePermission
from app.models.role import Role
from app.models.user import User
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
    ("documents:read", "Ver documentos"),
    ("documents:upload", "Subir documentos"),
    ("boards:read", "Ver tableros"),
    ("boards:manage", "Gestionar tableros"),
    ("credentials:read", "Ver credenciales cifradas"),
]

ROLES = {
    "ADMIN": {
        "name": "Administrador",
        "description": "Acceso total al sistema",
        "permissions": "*",
    },
    "AREA_LEADER": {
        "name": "Líder de área",
        "description": "Supervisa el trabajo de su área",
        "permissions": [
            "users:read",
            "clients:read",
            "clients:update",
            "documents:read",
            "boards:read",
            "boards:manage",
        ],
    },
    "SALES_REP": {
        "name": "Vendedor",
        "description": "Registra clientes nuevos",
        "permissions": ["clients:read", "clients:create", "clients:update"],
    },
    "ONBOARDING_MANAGER": {
        "name": "Encargado de Onboarding",
        "description": "Revisa y aprueba clientes, gestiona onboarding",
        "permissions": [
            "clients:read",
            "clients:update",
            "clients:approve",
            "documents:read",
            "boards:read",
            "boards:manage",
            "credentials:read",
        ],
    },
    "ADVISOR": {
        "name": "Asesor",
        "description": "Acompaña clientes asignados",
        "permissions": [
            "clients:read",
            "documents:read",
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
]

ADMIN_EMAIL = "admin@epoint.com"
ADMIN_PASSWORD = "Admin123!"

DEMO_USERS = [
    ("vendedor@epoint.com", "Vendedor", "Demo", "SALES_REP", "VENTAS", "Vendedor123!"),
    ("onboarding@epoint.com", "Encargado", "Onboarding", "ONBOARDING_MANAGER", "ONBOARDING", "Onboard123!"),
    ("asesor@epoint.com", "Asesor", "Demo", "ADVISOR", "ONBOARDING", "Asesor123!"),
]

BOARD_TEMPLATE = {
    "code": "DEFAULT_ONBOARDING",
    "name": "Onboarding estándar",
    "lists": [
        {"title": title, "position": index, "cards": []}
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

        # Áreas
        for code, name, desc in AREAS:
            area = db.execute(select(Area).where(Area.code == code)).scalar_one_or_none()
            if area is None:
                db.add(Area(code=code, name=name, description=desc))

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
            if db.execute(select(User).where(User.email == email)).scalar_one_or_none() is None:
                db.add(
                    User(
                        email=email,
                        password_hash=hash_password(pwd),
                        first_name=fname,
                        last_name=lname,
                        role_id=role_map[role_code].id,
                        area_id=area_map.get(area_code).id if area_code in area_map else None,
                        is_active=True,
                    )
                )

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
