"""Renombrar columnas Fonding/Founding a Funding

Revision ID: 052
Revises: 051
"""

from typing import Sequence, Union

from alembic import op

revision: str = "052"
down_revision: Union[str, None] = "051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RENAMES = (
    ("Personal Fonding Sequence", "Personal Funding Sequence"),
    ("Personal Fonding Sequence (2)", "Personal Funding Sequence (2)"),
    ("Business Founding Sequence", "Business Funding Sequence"),
    ("Business Founding Sequence (2)", "Business Funding Sequence (2)"),
)


def _rename(table: str) -> None:
    for old, new in RENAMES:
        op.execute(
            f"UPDATE {table} SET title = '{new}' WHERE title = '{old}'"
        )


def upgrade() -> None:
    _rename("board_lists")
    _rename("board_template_lists")
    op.execute(
        """
        DELETE FROM board_template_cards
        WHERE template_list_id IN (
            SELECT id FROM board_template_lists
            WHERE title IN (
                'Personal Funding Sequence',
                'Personal Funding Sequence (2)',
                'Business Funding Sequence',
                'Business Funding Sequence (2)',
                'Personal Fonding Sequence',
                'Personal Fonding Sequence (2)',
                'Business Founding Sequence',
                'Business Founding Sequence (2)'
            )
        )
        """
    )


def downgrade() -> None:
    for old, new in RENAMES:
        op.execute(
            f"UPDATE board_lists SET title = '{old}' WHERE title = '{new}'"
        )
        op.execute(
            f"UPDATE board_template_lists SET title = '{old}' WHERE title = '{new}'"
        )
