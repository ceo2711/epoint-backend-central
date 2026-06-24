"""Store encrypted portal temp password on client

Revision ID: 007
Revises: 006
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("portal_temp_password_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "portal_temp_password_encrypted")
