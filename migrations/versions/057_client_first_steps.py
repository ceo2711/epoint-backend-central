"""Primeros pasos del portal para clientes nuevos

Revision ID: 057
Revises: 056
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "057"
down_revision: Union[str, None] = "056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("first_steps_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Clientes ya existentes no deben ver el wizard; solo los que se den de alta después.
    op.execute(
        """
        UPDATE users
        SET first_steps_completed_at = NOW()
        WHERE first_steps_completed_at IS NULL
          AND role_id IN (SELECT id FROM roles WHERE code = 'CLIENT')
        """
    )


def downgrade() -> None:
    op.drop_column("users", "first_steps_completed_at")
