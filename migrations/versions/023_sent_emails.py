"""Sent emails log for prospects and clients

Revision ID: 023
Revises: 022
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sent_emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "prospect_id",
            sa.Integer(),
            sa.ForeignKey("prospects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("recipient_email", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("message_html", sa.Text(), nullable=False),
        sa.Column("sent_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sent_emails_prospect_id", "sent_emails", ["prospect_id"])
    op.create_index("ix_sent_emails_client_id", "sent_emails", ["client_id"])
    op.create_index("ix_sent_emails_sent_by_user_id", "sent_emails", ["sent_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_sent_emails_sent_by_user_id", table_name="sent_emails")
    op.drop_index("ix_sent_emails_client_id", table_name="sent_emails")
    op.drop_index("ix_sent_emails_prospect_id", table_name="sent_emails")
    op.drop_table("sent_emails")
