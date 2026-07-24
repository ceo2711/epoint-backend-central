"""Create influencers catalog and link to prospects

Revision ID: 034
Revises: 033
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "034"
down_revision: Union[str, None] = "033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "influencers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("handle", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sede_id", sa.Integer(), sa.ForeignKey("sedes.id"), nullable=False),
        sa.Column("sales_rep_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_influencers_sede_id", "influencers", ["sede_id"])
    op.create_index("ix_influencers_sales_rep_user_id", "influencers", ["sales_rep_user_id"])
    op.create_index("ix_influencers_created_by_user_id", "influencers", ["created_by_user_id"])

    op.add_column(
        "prospects",
        sa.Column(
            "influencer_id",
            sa.Integer(),
            sa.ForeignKey("influencers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_prospects_influencer_id", "prospects", ["influencer_id"])


def downgrade() -> None:
    op.drop_index("ix_prospects_influencer_id", table_name="prospects")
    op.drop_column("prospects", "influencer_id")
    op.drop_index("ix_influencers_created_by_user_id", table_name="influencers")
    op.drop_index("ix_influencers_sales_rep_user_id", table_name="influencers")
    op.drop_index("ix_influencers_sede_id", table_name="influencers")
    op.drop_table("influencers")
