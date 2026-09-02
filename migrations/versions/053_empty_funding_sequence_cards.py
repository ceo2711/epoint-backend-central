"""Vaciar cards de las columnas de funding sequence

Revision ID: 053
Revises: 052
"""

from typing import Sequence, Union

from alembic import op

revision: str = "053"
down_revision: Union[str, None] = "052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FUNDING_TITLES = (
    "Personal Funding Sequence",
    "Personal Funding Sequence (2)",
    "Business Funding Sequence",
    "Business Funding Sequence (2)",
    "Personal Fonding Sequence",
    "Personal Fonding Sequence (2)",
    "Business Founding Sequence",
    "Business Founding Sequence (2)",
)

_TITLES_SQL = ", ".join(f"'{title}'" for title in FUNDING_TITLES)


def upgrade() -> None:
    op.execute(
        f"""
        DELETE FROM board_cards
        WHERE list_id IN (
            SELECT id FROM board_lists
            WHERE title IN ({_TITLES_SQL})
        )
        """
    )
    op.execute(
        f"""
        DELETE FROM board_template_cards
        WHERE template_list_id IN (
            SELECT id FROM board_template_lists
            WHERE title IN ({_TITLES_SQL})
        )
        """
    )


def downgrade() -> None:
    pass
