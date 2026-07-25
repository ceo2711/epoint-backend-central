"""Rename LISTO_PARA_TABLERO → LISTO_PARA_TRABAJAR

Revision ID: 038
Revises: 037
"""

from typing import Sequence, Union

from alembic import op

revision: str = "038"
down_revision: Union[str, None] = "037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE clients SET status = 'LISTO_PARA_TRABAJAR' WHERE status = 'LISTO_PARA_TABLERO'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE clients SET status = 'LISTO_PARA_TABLERO' WHERE status = 'LISTO_PARA_TRABAJAR'"
    )
