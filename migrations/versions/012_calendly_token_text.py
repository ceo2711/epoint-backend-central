"""Widen Calendly encrypted token column

Revision ID: 012
Revises: 011
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "calendly_connections",
        "access_token_encrypted",
        existing_type=sa.String(length=1024),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "calendly_connections",
        "access_token_encrypted",
        existing_type=sa.Text(),
        type_=sa.String(length=1024),
        existing_nullable=False,
    )
