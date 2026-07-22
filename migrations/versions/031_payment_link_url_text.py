"""Widen payment link URL/token columns for Authorize.net hosted tokens

Revision ID: 031
Revises: 030
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "031"
down_revision: Union[str, None] = "030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "payment_links",
        "payment_url",
        existing_type=sa.String(length=512),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "payment_links",
        "external_checkout_id",
        existing_type=sa.String(length=128),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "payment_links",
        "external_checkout_url",
        existing_type=sa.String(length=512),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "payment_links",
        "external_checkout_url",
        existing_type=sa.Text(),
        type_=sa.String(length=512),
        existing_nullable=True,
    )
    op.alter_column(
        "payment_links",
        "external_checkout_id",
        existing_type=sa.Text(),
        type_=sa.String(length=128),
        existing_nullable=True,
    )
    op.alter_column(
        "payment_links",
        "payment_url",
        existing_type=sa.Text(),
        type_=sa.String(length=512),
        existing_nullable=False,
    )
