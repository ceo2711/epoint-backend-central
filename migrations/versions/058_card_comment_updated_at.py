"""Marca de edición en comentarios del tablero

Revision ID: 058
Revises: 057
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "058"
down_revision: Union[str, None] = "057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "card_comments",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("card_comments", "updated_at")
