"""User-merchant memberships and workspace context

Revision ID: 020
Revises: 019
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_merchants",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "merchant_id"),
    )
    op.create_index("ix_user_merchants_merchant_id", "user_merchants", ["merchant_id"])

    op.add_column("users", sa.Column("active_merchant_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_users_active_merchant_id",
        "users",
        "merchants",
        ["active_merchant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_users_active_merchant_id", "users", ["active_merchant_id"])

    op.add_column("payment_links", sa.Column("merchant_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_payment_links_merchant_id",
        "payment_links",
        "merchants",
        ["merchant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_payment_links_merchant_id", "payment_links", ["merchant_id"])

    op.add_column("docusign_envelopes", sa.Column("merchant_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_docusign_envelopes_merchant_id",
        "docusign_envelopes",
        "merchants",
        ["merchant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_docusign_envelopes_merchant_id", "docusign_envelopes", ["merchant_id"])

    op.execute(
        """
        UPDATE payment_links pl
        SET merchant_id = c.merchant_id
        FROM clients c
        WHERE pl.client_id = c.id AND pl.merchant_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE docusign_envelopes de
        SET merchant_id = c.merchant_id
        FROM clients c
        WHERE de.client_id = c.id AND de.merchant_id IS NULL
        """
    )

    op.execute(
        """
        INSERT INTO user_merchants (user_id, merchant_id)
        SELECT u.id, m.id
        FROM users u
        CROSS JOIN merchants m
        JOIN roles r ON r.id = u.role_id
        WHERE r.code != 'CLIENT' AND m.is_active = true
        ON CONFLICT DO NOTHING
        """
    )

    op.execute(
        """
        UPDATE users u
        SET active_merchant_id = (
            SELECT m.id FROM merchants m WHERE m.is_active = true ORDER BY m.id LIMIT 1
        )
        FROM roles r
        WHERE r.id = u.role_id
          AND r.code != 'CLIENT'
          AND u.active_merchant_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_docusign_envelopes_merchant_id", table_name="docusign_envelopes")
    op.drop_constraint("fk_docusign_envelopes_merchant_id", "docusign_envelopes", type_="foreignkey")
    op.drop_column("docusign_envelopes", "merchant_id")

    op.drop_index("ix_payment_links_merchant_id", table_name="payment_links")
    op.drop_constraint("fk_payment_links_merchant_id", "payment_links", type_="foreignkey")
    op.drop_column("payment_links", "merchant_id")

    op.drop_index("ix_users_active_merchant_id", table_name="users")
    op.drop_constraint("fk_users_active_merchant_id", "users", type_="foreignkey")
    op.drop_column("users", "active_merchant_id")

    op.drop_index("ix_user_merchants_merchant_id", table_name="user_merchants")
    op.drop_table("user_merchants")
