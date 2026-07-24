"""Create sources catalog and seed defaults including Influencers

Revision ID: 033
Revises: 032
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "033"
down_revision: Union[str, None] = "032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_SOURCES = (
    ("WEB_PAGE", "Página web", "Origen desde el sitio web", 10),
    ("WHATSAPP", "WhatsApp", None, 20),
    ("FACEBOOK", "Facebook", None, 30),
    ("INSTAGRAM", "Instagram", None, 40),
    ("REFERRAL", "Referido", None, 50),
    ("PHONE_CALL", "Llamada telefónica", None, 60),
    ("INFLUENCERS", "Influencers", "Referidos por influencers / creadores", 70),
    ("OTHER", "Otro", None, 90),
)

SOURCE_PERMISSIONS = (
    ("sources:read", "Ver sources"),
    ("sources:create", "Crear sources"),
    ("sources:update", "Editar sources"),
    ("sources:delete", "Desactivar sources"),
)


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_sources_code", "sources", ["code"], unique=True)

    conn = op.get_bind()
    for code, name, description, sort_order in DEFAULT_SOURCES:
        conn.execute(
            sa.text(
                """
                INSERT INTO sources (code, name, description, sort_order, is_active)
                VALUES (:code, :name, :description, :sort_order, true)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {
                "code": code,
                "name": name,
                "description": description,
                "sort_order": sort_order,
            },
        )

    for code, name in SOURCE_PERMISSIONS:
        conn.execute(
            sa.text(
                """
                INSERT INTO permissions (code, name)
                SELECT :code, :name
                WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = :code)
                """
            ),
            {"code": code, "name": name},
        )

    # Solo ADMIN recibe sources:*
    conn.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.code = 'ADMIN'
              AND p.code LIKE 'sources:%'
              AND NOT EXISTS (
                SELECT 1 FROM role_permissions rp
                WHERE rp.role_id = r.id AND rp.permission_id = p.id
              )
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            WHERE permission_id IN (SELECT id FROM permissions WHERE code LIKE 'sources:%')
            """
        )
    )
    conn.execute(sa.text("DELETE FROM permissions WHERE code LIKE 'sources:%'"))
    op.drop_index("ix_sources_code", table_name="sources")
    op.drop_table("sources")
