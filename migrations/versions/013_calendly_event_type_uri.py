"""Widen Calendly event metadata for scheduling API

Revision ID: 013
Revises: 012
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("calendly_events", sa.Column("event_type_uri", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("calendly_events", "event_type_uri")
