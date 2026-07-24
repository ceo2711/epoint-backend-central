"""Add label column to board_cards

Revision ID: 035
Revises: 034
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "035"
down_revision: Union[str, None] = "034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "board_cards",
        sa.Column("label", sa.String(length=30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("board_cards", "label")
