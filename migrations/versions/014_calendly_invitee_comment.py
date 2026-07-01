"""Add invitee comment to Calendly events

Revision ID: 014
Revises: 013
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("calendly_events", sa.Column("invitee_comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("calendly_events", "invitee_comment")
