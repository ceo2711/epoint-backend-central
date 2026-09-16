"""Acento neutro en copy de tarjetas de onboarding (usted).

Revision ID: 062
Revises: 061
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "062"
down_revision: Union[str, None] = "061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PHRASE_REPLACEMENTS = (
    (
        "Al finalizar, escribí el usuario y la contraseña en un **comentario**",
        "Al finalizar, escriba el usuario y la contraseña en un **comentario**",
    ),
    ("(dejálas en un comentario)", "(déjelas en un comentario)"),
    ("será rechazado y deberás descargar uno nuevo", "será rechazado y deberá descargar uno nuevo"),
    ("será rechazado y deberás volver a subirlo", "será rechazado y deberá volver a subirlo"),
    ("no creas un usuario y clave, solamente generas", "no cree un usuario y clave, solamente genere"),
    ("que debes adjuntar en su tarjeta", "que debe adjuntar en su tarjeta"),
    ("Cuando te lo soliciten", "Cuando se lo soliciten"),
    ("- Subí un documento fiscal legible", "- Suba un documento fiscal legible"),
    ("Ingresa a [Sign In | Innovis]", "Ingrese a [Sign In | Innovis]"),
    ("Selecciona la opción para solicitar tu **Innovis Credit Report**", "Seleccione la opción para solicitar su **Innovis Credit Report**"),
    ("como tu **Innovis.com Account**", "como su **Innovis.com Account**"),
    ("Completa el formulario con tus datos personales", "Complete el formulario con sus datos personales"),
    ("Verifica tu identidad. Innovis puede utilizar la información proporcionada para confirmar tu identidad, incluso mediante tu operador", "Verifique su identidad. Innovis puede utilizar la información proporcionada para confirmar su identidad, incluso mediante su operador"),
    ("te permitirá crear tu cuenta", "le permitirá crear su cuenta"),
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
    for old, new in _PHRASE_REPLACEMENTS:
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
