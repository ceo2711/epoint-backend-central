"""Pedir credenciales en comentarios de las tarjetas de onboarding.

Revision ID: 061
Revises: 060
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "061"
down_revision: Union[str, None] = "060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_FORM_NOTE = (
    "Al finalizar, cargá el usuario y la contraseña con el **formulario cifrado** de esta tarjeta. "
    "No los escribas en comentarios."
)
_OLD_FORM_NOTE_PLAIN = (
    "Al finalizar, cargá el usuario y la contraseña con el formulario cifrado de esta tarjeta. "
    "No los escribas en comentarios."
)
_NEW_FORM_NOTE = (
    "Al finalizar, escribí el usuario y la contraseña en un **comentario** de esta tarjeta "
    "para que un asesor pueda tomarlos."
)
_OLD_ACCOUNTS_NOTE = (
    "Las claves de ChexSystems e Innovis van en las tarjetas de la columna **Credenciales** "
    "(formulario cifrado)."
)
_NEW_ACCOUNTS_NOTE = (
    "Las claves de ChexSystems e Innovis van en las tarjetas de la columna **Credenciales** "
    "(dejálas en un comentario)."
)


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


def _replace_leftover_phrases(conn, table: str) -> None:
    replacements = (
        (_OLD_FORM_NOTE, _NEW_FORM_NOTE),
        (_OLD_FORM_NOTE_PLAIN, _NEW_FORM_NOTE),
        (_OLD_ACCOUNTS_NOTE, _NEW_ACCOUNTS_NOTE),
    )
    for old, new in replacements:
        conn.execute(
            sa.text(
                f"""
                UPDATE {table}
                SET description_md = replace(description_md, :old, :new)
                WHERE description_md LIKE :pattern
                """
            ),
            {"old": old, "new": new, "pattern": f"%{old}%"},
        )


def upgrade() -> None:
    conn = op.get_bind()
    for table in ("board_cards", "board_template_cards"):
        _update_cards(conn, table)
        _replace_leftover_phrases(conn, table)


def downgrade() -> None:
    pass
