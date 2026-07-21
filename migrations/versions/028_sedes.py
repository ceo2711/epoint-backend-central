"""Add sedes and link merchants, users, clients, prospects

Revision ID: 028
Revises: 027
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sedes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_sedes_code", "sedes", ["code"], unique=True)

    # Sede por defecto para datos existentes
    op.execute(
        """
        INSERT INTO sedes (code, name, description, is_active)
        VALUES ('sede-principal', 'Sede Principal', 'Sede inicial del grupo Epoint', true)
        """
    )

    op.add_column("merchants", sa.Column("sede_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_merchants_sede_id", "merchants", "sedes", ["sede_id"], ["id"])
    op.create_index("ix_merchants_sede_id", "merchants", ["sede_id"])
    op.execute("UPDATE merchants SET sede_id = (SELECT id FROM sedes WHERE code = 'sede-principal' LIMIT 1)")
    op.alter_column("merchants", "sede_id", nullable=False)

    op.add_column("clients", sa.Column("sede_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_clients_sede_id", "clients", "sedes", ["sede_id"], ["id"])
    op.create_index("ix_clients_sede_id", "clients", ["sede_id"])
    op.execute(
        """
        UPDATE clients
        SET sede_id = COALESCE(
            (SELECT m.sede_id FROM merchants m WHERE m.id = clients.merchant_id),
            (SELECT id FROM sedes WHERE code = 'sede-principal' LIMIT 1)
        )
        """
    )

    op.add_column("prospects", sa.Column("sede_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_prospects_sede_id", "prospects", "sedes", ["sede_id"], ["id"])
    op.create_index("ix_prospects_sede_id", "prospects", ["sede_id"])
    op.execute(
        """
        UPDATE prospects
        SET sede_id = COALESCE(
            (SELECT m.sede_id FROM merchants m WHERE m.id = prospects.merchant_id),
            (SELECT id FROM sedes WHERE code = 'sede-principal' LIMIT 1)
        )
        """
    )
    op.alter_column("prospects", "sede_id", nullable=False)

    op.add_column("users", sa.Column("sede_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_users_sede_id", "users", "sedes", ["sede_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_users_sede_id", "users", ["sede_id"])
    # Staff operativo: asignar a la sede principal (CLIENT y ADMIN pueden quedar sin sede)
    op.execute(
        """
        UPDATE users
        SET sede_id = (SELECT id FROM sedes WHERE code = 'sede-principal' LIMIT 1)
        WHERE role_id IN (
            SELECT id FROM roles
            WHERE code IN ('SALES_REP', 'ADVISOR', 'ONBOARDING_MANAGER', 'AREA_LEADER')
        )
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_sede_id", "users", type_="foreignkey")
    op.drop_index("ix_users_sede_id", table_name="users")
    op.drop_column("users", "sede_id")

    op.drop_constraint("fk_prospects_sede_id", "prospects", type_="foreignkey")
    op.drop_index("ix_prospects_sede_id", table_name="prospects")
    op.drop_column("prospects", "sede_id")

    op.drop_constraint("fk_clients_sede_id", "clients", type_="foreignkey")
    op.drop_index("ix_clients_sede_id", table_name="clients")
    op.drop_column("clients", "sede_id")

    op.drop_constraint("fk_merchants_sede_id", "merchants", type_="foreignkey")
    op.drop_index("ix_merchants_sede_id", table_name="merchants")
    op.drop_column("merchants", "sede_id")

    op.drop_index("ix_sedes_code", table_name="sedes")
    op.drop_table("sedes")
