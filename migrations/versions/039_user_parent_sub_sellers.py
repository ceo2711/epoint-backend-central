"""Add parent_user_id for sales sub-sellers hierarchy

Revision ID: 039
Revises: 038
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "039"
down_revision: Union[str, None] = "038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "parent_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_users_parent_user_id", "users", ["parent_user_id"])


def downgrade() -> None:
    op.drop_index("ix_users_parent_user_id", table_name="users")
    op.drop_column("users", "parent_user_id")
