"""Card attachment AI verification

Revision ID: 008
Revises: 007
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "card_attachments",
        sa.Column("verification_status", sa.String(length=30), nullable=True),
    )
    op.create_index(
        "ix_card_attachments_verification_status",
        "card_attachments",
        ["verification_status"],
    )

    op.create_table(
        "card_attachment_verifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("attachment_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("ai_model", sa.String(length=80), nullable=True),
        sa.Column("raw_response", JSONB(), nullable=True),
        sa.Column("rejection_reasons", JSONB(), nullable=True),
        sa.Column("approval_reasons", JSONB(), nullable=True),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["attachment_id"], ["card_attachments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_card_attachment_verifications_attachment_id",
        "card_attachment_verifications",
        ["attachment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_card_attachment_verifications_attachment_id", table_name="card_attachment_verifications")
    op.drop_table("card_attachment_verifications")
    op.drop_index("ix_card_attachments_verification_status", table_name="card_attachments")
    op.drop_column("card_attachments", "verification_status")
