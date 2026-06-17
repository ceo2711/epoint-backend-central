"""Add mime_type and comment_id to card attachments

Revision ID: 005
Revises: 004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("card_attachments", sa.Column("mime_type", sa.String(length=100), nullable=True))
    op.add_column("card_attachments", sa.Column("comment_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_card_attachments_comment_id",
        "card_attachments",
        "card_comments",
        ["comment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_card_attachments_comment_id", "card_attachments", ["comment_id"])


def downgrade() -> None:
    op.drop_index("ix_card_attachments_comment_id", table_name="card_attachments")
    op.drop_constraint("fk_card_attachments_comment_id", "card_attachments", type_="foreignkey")
    op.drop_column("card_attachments", "comment_id")
    op.drop_column("card_attachments", "mime_type")
