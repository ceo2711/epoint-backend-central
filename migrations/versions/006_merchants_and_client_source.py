"""Add merchants table and client source/merchant fields

Revision ID: 006
Revises: 005
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "merchants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_merchants_code", "merchants", ["code"], unique=True)

    op.add_column("clients", sa.Column("source", sa.String(length=40), nullable=True))
    op.add_column("clients", sa.Column("merchant_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_clients_merchant_id", "clients", "merchants", ["merchant_id"], ["id"])
    op.create_index("ix_clients_source", "clients", ["source"])
    op.create_index("ix_clients_merchant_id", "clients", ["merchant_id"])


def downgrade() -> None:
    op.drop_index("ix_clients_merchant_id", table_name="clients")
    op.drop_index("ix_clients_source", table_name="clients")
    op.drop_constraint("fk_clients_merchant_id", "clients", type_="foreignkey")
    op.drop_column("clients", "merchant_id")
    op.drop_column("clients", "source")
    op.drop_index("ix_merchants_code", table_name="merchants")
    op.drop_table("merchants")
