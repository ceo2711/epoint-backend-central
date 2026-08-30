"""Mover Informe de Taxes fuera del onboarding obligatorio

Revision ID: 051
Revises: 050
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "051"
down_revision: Union[str, None] = "050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TAXES_TITLE = "Informe de Taxes"
SOURCE_COLUMN = "Client TO DO"
TARGET_COLUMN = "Ideas a realizar"
TAXES_DESCRIPTION = """**Descripción**

Esta tarjeta **no es obligatoria para completar el onboarding**.

El informe de taxes (Tax Return / declaración de impuestos o Tax Transcript del IRS de los últimos 2 años fiscales) se pide **solo cuando una entidad financiera lo requiera** más adelante.

Cuando te lo soliciten:
- Subí un documento fiscal legible (Form 1040, Tax Return, IRS Transcript u otro informe oficial)
- Debe verse el nombre del contribuyente
- Cubre los últimos 2 años fiscales

Si el archivo no es un informe de taxes válido, será rechazado y deberás volver a subirlo."""


def _move_cards(
    conn,
    *,
    lists_table: str,
    cards_table: str,
    list_fk: str,
    parent_fk: str,
    source_title: str,
    target_title: str,
    description_md: str | None = None,
) -> None:
    sources = conn.execute(
        sa.text(
            f"""
            SELECT source.id, source.{parent_fk}
            FROM {lists_table} AS source
            WHERE source.title = :source_title
            """
        ),
        {"source_title": source_title},
    ).fetchall()

    for source_id, parent_id in sources:
        target = conn.execute(
            sa.text(
                f"""
                SELECT id FROM {lists_table}
                WHERE {parent_fk} = :parent_id AND title = :target_title
                LIMIT 1
                """
            ),
            {"parent_id": parent_id, "target_title": target_title},
        ).fetchone()
        if target is None:
            next_position = conn.execute(
                sa.text(
                    f"""
                    SELECT COALESCE(MAX(position), -1) + 1
                    FROM {lists_table}
                    WHERE {parent_fk} = :parent_id
                    """
                ),
                {"parent_id": parent_id},
            ).scalar()
            conn.execute(
                sa.text(
                    f"""
                    INSERT INTO {lists_table} ({parent_fk}, title, position)
                    VALUES (:parent_id, :title, :position)
                    """
                ),
                {"parent_id": parent_id, "title": target_title, "position": next_position},
            )
            target = conn.execute(
                sa.text(
                    f"""
                    SELECT id FROM {lists_table}
                    WHERE {parent_fk} = :parent_id AND title = :target_title
                    LIMIT 1
                    """
                ),
                {"parent_id": parent_id, "target_title": target_title},
            ).fetchone()
        if target is None:
            continue

        target_id = target[0]
        cards = conn.execute(
            sa.text(
                f"""
                SELECT id FROM {cards_table}
                WHERE {list_fk} = :source_id AND title = :title
                ORDER BY position, id
                """
            ),
            {"source_id": source_id, "title": TAXES_TITLE},
        ).fetchall()
        if not cards:
            continue

        next_card_position = conn.execute(
            sa.text(
                f"""
                SELECT COALESCE(MAX(position), -1) + 1
                FROM {cards_table}
                WHERE {list_fk} = :list_id
                """
            ),
            {"list_id": target_id},
        ).scalar()

        for offset, (card_id,) in enumerate(cards):
            params = {
                "target_id": target_id,
                "position": next_card_position + offset,
                "card_id": card_id,
            }
            if description_md is None:
                conn.execute(
                    sa.text(
                        f"""
                        UPDATE {cards_table}
                        SET {list_fk} = :target_id, position = :position
                        WHERE id = :card_id
                        """
                    ),
                    params,
                )
            else:
                conn.execute(
                    sa.text(
                        f"""
                        UPDATE {cards_table}
                        SET {list_fk} = :target_id,
                            position = :position,
                            description_md = :description_md
                        WHERE id = :card_id
                        """
                    ),
                    {**params, "description_md": description_md},
                )


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE board_cards
            SET description_md = :description_md
            WHERE title = :title
            """
        ),
        {"description_md": TAXES_DESCRIPTION, "title": TAXES_TITLE},
    )
    conn.execute(
        sa.text(
            """
            UPDATE board_template_cards
            SET description_md = :description_md
            WHERE title = :title
            """
        ),
        {"description_md": TAXES_DESCRIPTION, "title": TAXES_TITLE},
    )
    _move_cards(
        conn,
        lists_table="board_lists",
        cards_table="board_cards",
        list_fk="list_id",
        parent_fk="board_id",
        source_title=SOURCE_COLUMN,
        target_title=TARGET_COLUMN,
        description_md=TAXES_DESCRIPTION,
    )
    _move_cards(
        conn,
        lists_table="board_template_lists",
        cards_table="board_template_cards",
        list_fk="template_list_id",
        parent_fk="template_id",
        source_title=SOURCE_COLUMN,
        target_title=TARGET_COLUMN,
        description_md=TAXES_DESCRIPTION,
    )


def downgrade() -> None:
    conn = op.get_bind()
    _move_cards(
        conn,
        lists_table="board_lists",
        cards_table="board_cards",
        list_fk="list_id",
        parent_fk="board_id",
        source_title=TARGET_COLUMN,
        target_title=SOURCE_COLUMN,
    )
    _move_cards(
        conn,
        lists_table="board_template_lists",
        cards_table="board_template_cards",
        list_fk="template_list_id",
        parent_fk="template_id",
        source_title=TARGET_COLUMN,
        target_title=SOURCE_COLUMN,
    )
