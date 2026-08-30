"""Pagos parciales: saldo, flag y recordatorio

Revision ID: 047
Revises: 046
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "047"
down_revision: Union[str, None] = "046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_links",
        sa.Column("allow_partial", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "payment_links",
        sa.Column("amount_paid", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "payment_links",
        sa.Column("pending_charge_amount", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "payment_links",
        sa.Column("last_payment_reminder_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payment_links", "last_payment_reminder_at")
    op.drop_column("payment_links", "pending_charge_amount")
    op.drop_column("payment_links", "amount_paid")
    op.drop_column("payment_links", "allow_partial")
