"""Marcar pagos parciales en prospectos

Revision ID: 049
Revises: 048
"""

from typing import Sequence, Union

from alembic import op

revision: str = "049"
down_revision: Union[str, None] = "048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE prospects
        SET status = 'PAGO_PARCIAL'
        WHERE status = 'PAGO_COMPLETADO'
          AND COALESCE((
            SELECT SUM(payment_links.amount_paid)
            FROM payment_links
            WHERE payment_links.prospect_id = prospects.id
          ), 0) > 0
          AND COALESCE((
            SELECT SUM(payment_links.amount_paid)
            FROM payment_links
            WHERE payment_links.prospect_id = prospects.id
          ), 0) < 3000
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE prospects
        SET status = 'PAGO_COMPLETADO'
        WHERE status = 'PAGO_PARCIAL'
        """
    )
