"""DocuSign signed PDF storage and completion notification tracking

Revision ID: 017
Revises: 016
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "docusign_envelopes",
        sa.Column("signed_storage_key", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "docusign_envelopes",
        sa.Column("signed_document_filename", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "docusign_envelopes",
        sa.Column("completion_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("docusign_envelopes", "completion_notified_at")
    op.drop_column("docusign_envelopes", "signed_document_filename")
    op.drop_column("docusign_envelopes", "signed_storage_key")
