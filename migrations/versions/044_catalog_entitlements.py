"""Cursos/mentorías: catálogo, entitlements y product_code en payment links.

Revision ID: 044
Revises: 043
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "044"
down_revision: Union[str, None] = "043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("calendly_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_catalog_products_code", "catalog_products", ["code"])

    op.add_column("payment_links", sa.Column("product_code", sa.String(length=40), nullable=True))
    op.create_index("ix_payment_links_product_code", "payment_links", ["product_code"])

    op.create_table(
        "client_entitlements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("product_code", sa.String(length=40), nullable=False),
        sa.Column("payment_link_id", sa.Integer(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payment_link_id"], ["payment_links.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "product_code", name="uq_client_entitlements_client_product"),
    )
    op.create_index("ix_client_entitlements_client_id", "client_entitlements", ["client_id"])
    op.create_index("ix_client_entitlements_product_code", "client_entitlements", ["product_code"])
    op.create_index("ix_client_entitlements_payment_link_id", "client_entitlements", ["payment_link_id"])

    op.execute(
        """
        INSERT INTO catalog_products (code, name, description, amount, currency, is_active)
        VALUES
            ('COURSE', 'Programa de crédito en video', '12 módulos / 36 lecciones', 497.00, 'USD', TRUE),
            ('MENTORSHIP', 'Mentoría 1:1', 'Sesiones en vivo con un asesor', 997.00, 'USD', TRUE)
        ON CONFLICT (code) DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO sources (code, name, description, sort_order, is_active)
        SELECT 'LANDING', 'Landing EpointCredits', 'Compra desde epointcredits.com', 15, TRUE
        WHERE NOT EXISTS (SELECT 1 FROM sources WHERE code = 'LANDING')
        """
    )

    op.execute(
        """
        INSERT INTO permissions (code, name)
        SELECT 'courses:manage', 'Cargar y publicar cursos'
        WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'courses:manage')
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.code IN ('ADVISOR', 'ADMIN', 'BRANCH_MANAGER')
          AND p.code = 'courses:manage'
          AND NOT EXISTS (
            SELECT 1 FROM role_permissions rp
            WHERE rp.role_id = r.id AND rp.permission_id = p.id
          )
        """
    )

    # Clientes actuales son de asesoría crediticia.
    op.execute(
        """
        INSERT INTO client_entitlements (client_id, product_code)
        SELECT id, 'CREDIT' FROM clients
        WHERE NOT EXISTS (
            SELECT 1 FROM client_entitlements e
            WHERE e.client_id = clients.id AND e.product_code = 'CREDIT'
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'courses:manage')
        """
    )
    op.execute("DELETE FROM permissions WHERE code = 'courses:manage'")
    op.execute("DELETE FROM sources WHERE code = 'LANDING'")
    op.drop_index("ix_client_entitlements_payment_link_id", table_name="client_entitlements")
    op.drop_index("ix_client_entitlements_product_code", table_name="client_entitlements")
    op.drop_index("ix_client_entitlements_client_id", table_name="client_entitlements")
    op.drop_table("client_entitlements")
    op.drop_index("ix_payment_links_product_code", table_name="payment_links")
    op.drop_column("payment_links", "product_code")
    op.drop_index("ix_catalog_products_code", table_name="catalog_products")
    op.drop_table("catalog_products")
