"""Prospect/client qualification flag independent of pipeline status

Revision ID: 022
Revises: 021
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prospects",
        sa.Column("is_qualified", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "clients",
        sa.Column("is_qualified", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.execute(
        """
        UPDATE prospects
        SET is_qualified = false
        WHERE status = 'LEAD_NO_CALIFICADO'
        """
    )
    op.execute(
        """
        UPDATE prospects
        SET status = 'PENDIENTE_CONTACTAR'
        WHERE status IN ('LEAD_CALIFICADO', 'LEAD_NO_CALIFICADO')
        """
    )
    op.execute(
        """
        UPDATE clients AS c
        SET is_qualified = p.is_qualified
        FROM prospects AS p
        WHERE p.converted_client_id = c.id
        """
    )

    op.alter_column("prospects", "is_qualified", server_default=None)
    op.alter_column("clients", "is_qualified", server_default=None)


def downgrade() -> None:
    op.execute(
        """
        UPDATE prospects
        SET status = CASE
            WHEN is_qualified = false AND status = 'PENDIENTE_CONTACTAR' THEN 'LEAD_NO_CALIFICADO'
            WHEN is_qualified = true AND status = 'PENDIENTE_CONTACTAR' THEN 'LEAD_CALIFICADO'
            ELSE status
        END
        """
    )
    op.drop_column("clients", "is_qualified")
    op.drop_column("prospects", "is_qualified")
