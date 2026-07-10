"""Payment links and settings for Stripe/Authorize.net

Revision ID: 019
Revises: 018_client_docusign_contract
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019"
down_revision: Union[str, None] = "018_client_docusign_contract"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("default_provider", sa.String(length=20), server_default="stripe", nullable=False),
        sa.Column("payments_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO payment_settings (id, default_provider, payments_enabled) VALUES (1, 'stripe', true)"
    )

    op.create_table(
        "payment_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_token", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("customer_first_name", sa.String(length=100), nullable=False),
        sa.Column("customer_last_name", sa.String(length=100), nullable=False),
        sa.Column("customer_email", sa.String(length=255), nullable=False),
        sa.Column("customer_phone", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payment_url", sa.String(length=512), nullable=False),
        sa.Column("external_checkout_id", sa.String(length=128), nullable=True),
        sa.Column("external_checkout_url", sa.String(length=512), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_token"),
    )
    op.create_index("ix_payment_links_created_by_user_id", "payment_links", ["created_by_user_id"])
    op.create_index("ix_payment_links_client_id", "payment_links", ["client_id"])
    op.create_index("ix_payment_links_customer_email", "payment_links", ["customer_email"])
    op.create_index("ix_payment_links_status", "payment_links", ["status"])


def downgrade() -> None:
    op.drop_index("ix_payment_links_status", table_name="payment_links")
    op.drop_index("ix_payment_links_customer_email", table_name="payment_links")
    op.drop_index("ix_payment_links_client_id", table_name="payment_links")
    op.drop_index("ix_payment_links_created_by_user_id", table_name="payment_links")
    op.drop_table("payment_links")
    op.drop_table("payment_settings")
