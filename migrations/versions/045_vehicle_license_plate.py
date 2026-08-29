"""Add optional vehicle license plate (web only; mobile may omit it)

Revision ID: 045
Revises: 044
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "045"
down_revision: Union[str, None] = "044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("license_plate", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("vehicles", "license_plate")
