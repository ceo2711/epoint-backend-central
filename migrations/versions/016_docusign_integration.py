"""DocuSign company connection and sent envelopes

Revision ID: 016
Revises: 015
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "docusign_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("integration_key", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("impersonated_user_id", sa.String(length=64), nullable=False),
        sa.Column("impersonated_user_email", sa.String(length=255), nullable=True),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("base_uri", sa.String(length=255), nullable=False),
        sa.Column("auth_server", sa.String(length=120), server_default="account-d.docusign.com", nullable=False),
        sa.Column("private_key_encrypted", sa.Text(), nullable=False),
        sa.Column("default_template_id", sa.String(length=64), nullable=True),
        sa.Column("default_template_role_name", sa.String(length=120), server_default="Signer", nullable=False),
        sa.Column("connected_by_user_id", sa.Integer(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["connected_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "docusign_envelopes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("docusign_envelope_id", sa.String(length=64), nullable=False),
        sa.Column("sent_by_user_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("signer_name", sa.String(length=255), nullable=False),
        sa.Column("signer_email", sa.String(length=255), nullable=False),
        sa.Column("template_id", sa.String(length=64), nullable=False),
        sa.Column("template_role_name", sa.String(length=120), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="sent", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["sent_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("docusign_envelope_id"),
    )
    op.create_index("ix_docusign_envelopes_sent_by_user_id", "docusign_envelopes", ["sent_by_user_id"])
    op.create_index("ix_docusign_envelopes_client_id", "docusign_envelopes", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_docusign_envelopes_client_id", table_name="docusign_envelopes")
    op.drop_index("ix_docusign_envelopes_sent_by_user_id", table_name="docusign_envelopes")
    op.drop_table("docusign_envelopes")
    op.drop_table("docusign_connections")
