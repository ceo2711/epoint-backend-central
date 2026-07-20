"""Add users.avatar_storage_key

Revision ID: 027
Revises: 026
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("avatar_storage_key", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_storage_key")
