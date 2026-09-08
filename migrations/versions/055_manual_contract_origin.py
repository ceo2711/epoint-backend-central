"""Origen del contrato: DocuSign o carga manual

Revision ID: 055
Revises: 054
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "055"
down_revision: Union[str, None] = "054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "docusign_envelopes",
        sa.Column("origin", sa.String(length=20), nullable=False, server_default="docusign"),
    )


def downgrade() -> None:
    op.drop_column("docusign_envelopes", "origin")
