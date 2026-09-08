"""Calificación de lead opcional (se puede cargar después)

Revision ID: 056
Revises: 055
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "056"
down_revision: Union[str, None] = "055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("prospects", "is_qualified", existing_type=sa.Boolean(), nullable=True)
    op.alter_column("clients", "is_qualified", existing_type=sa.Boolean(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE prospects SET is_qualified = true WHERE is_qualified IS NULL")
    op.execute("UPDATE clients SET is_qualified = true WHERE is_qualified IS NULL")
    op.alter_column("prospects", "is_qualified", existing_type=sa.Boolean(), nullable=False)
    op.alter_column("clients", "is_qualified", existing_type=sa.Boolean(), nullable=False)
