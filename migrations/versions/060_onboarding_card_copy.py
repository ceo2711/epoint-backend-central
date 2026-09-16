"""Actualizar copy de tarjetas de onboarding (reportes, burós, bancos).

Revision ID: 060
Revises: 059
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "060"
down_revision: Union[str, None] = "059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _update_cards(conn, table: str) -> None:
    from app.constants.default_board_cards import CARD_TITLE_ALIASES, DEFAULT_BOARD_CARDS_BY_COLUMN

    for cards in DEFAULT_BOARD_CARDS_BY_COLUMN.values():
        for card in cards:
            old_titles = [old for old, new in CARD_TITLE_ALIASES.items() if new == card.title]
            for title in (card.title, *old_titles):
                conn.execute(
                    sa.text(
                        f"""
                        UPDATE {table}
                        SET title = :new_title,
                            description_md = :description_md,
                            requires_credentials = :requires_credentials,
                            requires_file_upload = :requires_file_upload
                        WHERE title = :old_title
                        """
                    ),
                    {
                        "old_title": title,
                        "new_title": card.title,
                        "description_md": card.description_md or None,
                        "requires_credentials": card.requires_credentials,
                        "requires_file_upload": card.requires_file_upload,
                    },
                )


def upgrade() -> None:
    conn = op.get_bind()
    _update_cards(conn, "board_cards")
    _update_cards(conn, "board_template_cards")


def downgrade() -> None:
    pass
