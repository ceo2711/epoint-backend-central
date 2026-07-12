"""Elimina todos los registros de clientes y desactiva usuarios portal (rol CLIENT).

No toca merchants, staff, contratos DocuSign, links de pago ni plantillas de tablero.
Uso: python scripts/purge_all_clients.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select, update

from app.core.database import SessionLocal
from app.models.client import Client
from app.models.role import Role
from app.models.user import User


def main() -> None:
    db = SessionLocal()
    try:
        total = db.execute(select(func.count()).select_from(Client)).scalar_one()
        if total == 0:
            print("No hay clientes en la base de datos.")
            return

        print(f"Clientes a eliminar: {total}")

        portal_user_ids = db.execute(
            select(User.id).join(Role, User.role_id == Role.id).where(Role.code == "CLIENT")
        ).scalars().all()
        if portal_user_ids:
            db.execute(
                update(User)
                .where(User.id.in_(portal_user_ids))
                .values(client_id=None, is_active=False)
            )
            print(f"Usuarios portal desvinculados/desactivados: {len(portal_user_ids)}")

        db.execute(update(Client).values(docusign_envelope_id=None))
        db.flush()

        deleted = db.execute(delete(Client))
        db.commit()

        print(f"Clientes eliminados: {deleted.rowcount or total}")
        remaining = db.execute(select(func.count()).select_from(Client)).scalar_one()
        print(f"Clientes restantes: {remaining}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
