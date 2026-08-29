"""Clarify board card copy, credentials forms, taxes years, and Inquiries cards

Revision ID: 044
Revises: 043
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "044"
down_revision: Union[str, None] = "043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TAXES_TITLE = "Informe de Taxes"
TAXES_DESCRIPTION = """**Descripción**

Sube tu informe de taxes de los **últimos 2 años fiscales** (Tax Return / declaración de impuestos o Tax Transcript del IRS) en PDF o imagen clara.

**Requisitos:**
- Debe verse el nombre del contribuyente
- Debe ser un documento fiscal legible (Form 1040, Tax Return, IRS Transcript u otro informe de taxes oficial)
- Cubre los últimos 2 años fiscales
- Prefiere archivos recién generados o del año fiscal correspondiente

Si el archivo no es un informe de taxes válido, será rechazado y deberás volver a subirlo."""

FREEZE_CREDENTIALS_NOTE = """
**Credenciales de esta tarjeta**

Usa el formulario cifrado de abajo para **ChexSystems, Innovis y Clarity Services**.

Las claves de Experian, Equifax y TransUnion van en las tarjetas de la columna **Credenciales**."""

INQUIRIES_DESCRIPTION = """**Descripción**

Lista las inquiries (consultas de crédito) de este buró: acreedor, fecha y tipo (hard/soft)."""

CREDENTIAL_TITLES = ("Experian", "Equifax", "TransUnion", "ChexSystems", "Innovis")
BUREAU_COLUMNS = ("Experian", "Transunion", "Equifax")


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
        {"title": TAXES_TITLE, "description_md": TAXES_DESCRIPTION},
    )

    freeze_cards = conn.execute(
        sa.text(
            """
            SELECT id, description_md
            FROM board_cards
            WHERE title = 'Apertura de Cuentas & Freeze'
            """
        )
    ).fetchall()
    for card_id, description_md in freeze_cards:
        current = description_md or ""
        if "ChexSystems, Innovis y Clarity" in current:
            continue
        conn.execute(
            sa.text("UPDATE board_cards SET description_md = :description_md WHERE id = :id"),
            {"id": card_id, "description_md": current.rstrip() + "\n" + FREEZE_CREDENTIALS_NOTE},
        )

    conn.execute(
        sa.text(
            """
            UPDATE board_cards AS c
            SET requires_credentials = true
            FROM board_lists AS l
            WHERE c.list_id = l.id
              AND l.title = 'Credenciales'
              AND c.title IN ('Experian', 'Equifax', 'TransUnion', 'ChexSystems', 'Innovis')
            """
        )
    )

    for column_title in BUREAU_COLUMNS:
        lists = conn.execute(
            sa.text("SELECT id FROM board_lists WHERE title = :title"),
            {"title": column_title},
        ).fetchall()
        for (list_id,) in lists:
            exists = conn.execute(
                sa.text(
                    """
                    SELECT 1
                    FROM board_cards
                    WHERE list_id = :list_id AND lower(title) = 'inquiries'
                    LIMIT 1
                    """
                ),
                {"list_id": list_id},
            ).scalar()
            if exists:
                continue
            max_pos = conn.execute(
                sa.text("SELECT COALESCE(MAX(position), -1) FROM board_cards WHERE list_id = :list_id"),
                {"list_id": list_id},
            ).scalar()
            conn.execute(
                sa.text(
                    """
                    INSERT INTO board_cards (
                        list_id, title, description_md, status, position,
                        requires_credentials, requires_file_upload
                    )
                    VALUES (
                        :list_id, 'Inquiries', :description_md, 'PENDIENTE', :position,
                        false, false
                    )
                    """
                ),
                {
                    "list_id": list_id,
                    "description_md": INQUIRIES_DESCRIPTION,
                    "position": int(max_pos) + 1,
                },
            )

    conn.execute(
        sa.text(
            """
            UPDATE board_template_cards
            SET description_md = :description_md
            WHERE title = :title
            """
        ),
        {"title": TAXES_TITLE, "description_md": TAXES_DESCRIPTION},
    )
    conn.execute(
        sa.text(
            """
            UPDATE board_template_cards AS c
            SET requires_credentials = true
            FROM board_template_lists AS l
            WHERE c.template_list_id = l.id
              AND l.title = 'Credenciales'
              AND c.title IN ('Experian', 'Equifax', 'TransUnion', 'ChexSystems', 'Innovis')
            """
        )
    )

    freeze_templates = conn.execute(
        sa.text(
            """
            SELECT id, description_md
            FROM board_template_cards
            WHERE title = 'Apertura de Cuentas & Freeze'
            """
        )
    ).fetchall()
    for card_id, description_md in freeze_templates:
        current = description_md or ""
        if "ChexSystems, Innovis y Clarity" in current:
            continue
        conn.execute(
            sa.text("UPDATE board_template_cards SET description_md = :description_md WHERE id = :id"),
            {"id": card_id, "description_md": current.rstrip() + "\n" + FREEZE_CREDENTIALS_NOTE},
        )

    for column_title in BUREAU_COLUMNS:
        lists = conn.execute(
            sa.text("SELECT id FROM board_template_lists WHERE title = :title"),
            {"title": column_title},
        ).fetchall()
        for (list_id,) in lists:
            exists = conn.execute(
                sa.text(
                    """
                    SELECT 1
                    FROM board_template_cards
                    WHERE template_list_id = :list_id AND lower(title) = 'inquiries'
                    LIMIT 1
                    """
                ),
                {"list_id": list_id},
            ).scalar()
            if exists:
                continue
            max_pos = conn.execute(
                sa.text(
                    "SELECT COALESCE(MAX(position), -1) FROM board_template_cards WHERE template_list_id = :list_id"
                ),
                {"list_id": list_id},
            ).scalar()
            conn.execute(
                sa.text(
                    """
                    INSERT INTO board_template_cards (
                        template_list_id, title, description_md, position,
                        requires_credentials, requires_file_upload
                    )
                    VALUES (
                        :list_id, 'Inquiries', :description_md, :position,
                        false, false
                    )
                    """
                ),
                {
                    "list_id": list_id,
                    "description_md": INQUIRIES_DESCRIPTION,
                    "position": int(max_pos) + 1,
                },
            )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE board_cards AS c
            SET requires_credentials = false
            FROM board_lists AS l
            WHERE c.list_id = l.id
              AND l.title = 'Credenciales'
              AND c.title IN ('Experian', 'Equifax', 'TransUnion', 'ChexSystems', 'Innovis')
            """
        )
    )
