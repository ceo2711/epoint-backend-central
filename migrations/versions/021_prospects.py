"""Prospects pipeline and integration links

Revision ID: 021
Revises: 020
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prospects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("merchant_id", sa.Integer(), nullable=False),
        sa.Column("assigned_to_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("converted_client_id", sa.Integer(), nullable=True),
        sa.Column("calendly_event_id", sa.Integer(), nullable=True),
        sa.Column("docusign_envelope_id", sa.Integer(), nullable=True),
        sa.Column("payment_link_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["assigned_to_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["calendly_event_id"], ["calendly_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["converted_client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["docusign_envelope_id"], ["docusign_envelopes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.ForeignKeyConstraint(["payment_link_id"], ["payment_links.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prospects_merchant_id", "prospects", ["merchant_id"])
    op.create_index("ix_prospects_assigned_to_user_id", "prospects", ["assigned_to_user_id"])
    op.create_index("ix_prospects_status", "prospects", ["status"])
    op.create_index("ix_prospects_email", "prospects", ["email"])
    op.create_index("ix_prospects_converted_client_id", "prospects", ["converted_client_id"])

    op.create_table(
        "prospect_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prospect_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.String(length=40), nullable=True),
        sa.Column("to_status", sa.String(length=40), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["changed_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["prospect_id"], ["prospects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prospect_history_prospect_id", "prospect_history", ["prospect_id"])

    op.add_column("calendly_events", sa.Column("prospect_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_calendly_events_prospect_id",
        "calendly_events",
        "prospects",
        ["prospect_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_calendly_events_prospect_id", "calendly_events", ["prospect_id"])

    op.add_column("docusign_envelopes", sa.Column("prospect_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_docusign_envelopes_prospect_id",
        "docusign_envelopes",
        "prospects",
        ["prospect_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_docusign_envelopes_prospect_id", "docusign_envelopes", ["prospect_id"])

    op.add_column("payment_links", sa.Column("prospect_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_payment_links_prospect_id",
        "payment_links",
        "prospects",
        ["prospect_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_payment_links_prospect_id", "payment_links", ["prospect_id"])


def downgrade() -> None:
    op.drop_index("ix_payment_links_prospect_id", table_name="payment_links")
    op.drop_constraint("fk_payment_links_prospect_id", "payment_links", type_="foreignkey")
    op.drop_column("payment_links", "prospect_id")

    op.drop_index("ix_docusign_envelopes_prospect_id", table_name="docusign_envelopes")
    op.drop_constraint("fk_docusign_envelopes_prospect_id", "docusign_envelopes", type_="foreignkey")
    op.drop_column("docusign_envelopes", "prospect_id")

    op.drop_index("ix_calendly_events_prospect_id", table_name="calendly_events")
    op.drop_constraint("fk_calendly_events_prospect_id", "calendly_events", type_="foreignkey")
    op.drop_column("calendly_events", "prospect_id")

    op.drop_index("ix_prospect_history_prospect_id", table_name="prospect_history")
    op.drop_table("prospect_history")

    op.drop_index("ix_prospects_converted_client_id", table_name="prospects")
    op.drop_index("ix_prospects_email", table_name="prospects")
    op.drop_index("ix_prospects_status", table_name="prospects")
    op.drop_index("ix_prospects_assigned_to_user_id", table_name="prospects")
    op.drop_index("ix_prospects_merchant_id", table_name="prospects")
    op.drop_table("prospects")
