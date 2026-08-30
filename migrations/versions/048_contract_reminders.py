"""Recordatorios de contratos pendientes de firma

Revision ID: 048
Revises: 047
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "048"
down_revision: Union[str, None] = "047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "docusign_envelopes",
        sa.Column("last_contract_reminder_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("docusign_envelopes", "last_contract_reminder_at")
