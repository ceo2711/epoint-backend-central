"""Fecha acordada para completar el saldo de un pago parcial

Revision ID: 054
Revises: 053
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "054"
down_revision: Union[str, None] = "053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_links",
        sa.Column("remainder_due_on", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payment_links", "remainder_due_on")
