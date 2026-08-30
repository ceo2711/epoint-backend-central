"""Client email inbox: inbound direction, read state, Resend id

Revision ID: 046
Revises: 045
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "046"
down_revision: Union[str, None] = "045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sent_emails",
        sa.Column("from_email", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "sent_emails",
        sa.Column("direction", sa.String(length=16), nullable=False, server_default="OUTBOUND"),
    )
    op.add_column(
        "sent_emails",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sent_emails",
        sa.Column("resend_email_id", sa.String(length=64), nullable=True),
    )
    op.alter_column("sent_emails", "sent_by_user_id", existing_type=sa.Integer(), nullable=True)
    op.create_index("ix_sent_emails_direction", "sent_emails", ["direction"])
    op.create_index("ix_sent_emails_resend_email_id", "sent_emails", ["resend_email_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_sent_emails_resend_email_id", table_name="sent_emails")
    op.drop_index("ix_sent_emails_direction", table_name="sent_emails")
    op.alter_column("sent_emails", "sent_by_user_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("sent_emails", "resend_email_id")
    op.drop_column("sent_emails", "read_at")
    op.drop_column("sent_emails", "direction")
    op.drop_column("sent_emails", "from_email")
