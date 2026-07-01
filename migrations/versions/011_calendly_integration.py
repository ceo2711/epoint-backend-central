"""Calendly connections and synced events

Revision ID: 011
Revises: 010
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calendly_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("calendly_user_uri", sa.String(length=255), nullable=False),
        sa.Column("calendly_user_name", sa.String(length=255), nullable=False),
        sa.Column("calendly_user_slug", sa.String(length=120), nullable=True),
        sa.Column("scheduling_url", sa.String(length=500), nullable=False),
        sa.Column("access_token_encrypted", sa.String(length=1024), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_calendly_connections_user_id", "calendly_connections", ["user_id"])

    op.create_table(
        "calendly_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("calendly_event_uri", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type_name", sa.String(length=255), nullable=True),
        sa.Column("invitee_name", sa.String(length=255), nullable=True),
        sa.Column("invitee_email", sa.String(length=255), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("meeting_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("calendly_event_uri"),
    )
    op.create_index("ix_calendly_events_user_id", "calendly_events", ["user_id"])
    op.create_index("ix_calendly_events_start_time", "calendly_events", ["start_time"])


def downgrade() -> None:
    op.drop_index("ix_calendly_events_start_time", table_name="calendly_events")
    op.drop_index("ix_calendly_events_user_id", table_name="calendly_events")
    op.drop_table("calendly_events")
    op.drop_index("ix_calendly_connections_user_id", table_name="calendly_connections")
    op.drop_table("calendly_connections")
