"""Default board card label to PENDIENTE and backfill existing rows

Revision ID: 036
Revises: 035
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "036"
down_revision: Union[str, None] = "035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE board_cards SET label = 'PENDIENTE' WHERE label IS NULL")
    )
    op.alter_column(
        "board_cards",
        "label",
        existing_type=sa.String(length=30),
        server_default="PENDIENTE",
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "board_cards",
        "label",
        existing_type=sa.String(length=30),
        server_default=None,
        existing_nullable=True,
    )
