"""Add sedes.avatar_storage_key

Revision ID: 029
Revises: 028
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sedes",
        sa.Column("avatar_storage_key", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sedes", "avatar_storage_key")
