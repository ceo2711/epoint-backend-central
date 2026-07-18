"""Add Informe de Taxes card to existing Client TO DO lists

Revision ID: 025
Revises: 024
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TAXES_TITLE = "Informe de Taxes"
TAXES_DESCRIPTION = """**Descripción**

Subí tu informe de taxes (Tax Return / declaración de impuestos o Tax Transcript del IRS) en PDF o imagen clara.

**Requisitos:**
- Debe verse el nombre del contribuyente
- Debe ser un documento fiscal legible (Form 1040, Tax Return, IRS Transcript u otro informe de taxes oficial)
- Preferí archivos recién generados o del año fiscal correspondiente

Si el archivo no es un informe de taxes válido, será rechazado y deberás volver a subirlo."""


def upgrade() -> None:
    conn = op.get_bind()

    # Tableros de clientes ya creados
    lists = conn.execute(
        sa.text(
            """
            SELECT bl.id
            FROM board_lists bl
            WHERE bl.title = 'Client TO DO'
            """
        )
    ).fetchall()

    for (list_id,) in lists:
        exists = conn.execute(
            sa.text(
                """
                SELECT 1
                FROM board_cards
                WHERE list_id = :list_id
                  AND lower(title) LIKE '%tax%'
                LIMIT 1
                """
            ),
            {"list_id": list_id},
        ).scalar()
        if exists:
            continue

        conn.execute(
            sa.text(
                """
                UPDATE board_cards
                SET position = position + 1
                WHERE list_id = :list_id
                  AND position >= 1
                """
            ),
            {"list_id": list_id},
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO board_cards (
                    list_id, title, description_md, status, position,
                    requires_credentials, requires_file_upload
                )
                VALUES (
                    :list_id, :title, :description_md, 'PENDIENTE', 1,
                    false, true
                )
                """
            ),
            {
                "list_id": list_id,
                "title": TAXES_TITLE,
                "description_md": TAXES_DESCRIPTION,
            },
        )

    # Templates de onboarding (para clientes nuevos)
    template_lists = conn.execute(
        sa.text(
            """
            SELECT btl.id
            FROM board_template_lists btl
            WHERE btl.title = 'Client TO DO'
            """
        )
    ).fetchall()

    for (template_list_id,) in template_lists:
        exists = conn.execute(
            sa.text(
                """
                SELECT 1
                FROM board_template_cards
                WHERE template_list_id = :template_list_id
                  AND lower(title) LIKE '%tax%'
                LIMIT 1
                """
            ),
            {"template_list_id": template_list_id},
        ).scalar()
        if exists:
            continue

        conn.execute(
            sa.text(
                """
                UPDATE board_template_cards
                SET position = position + 1
                WHERE template_list_id = :template_list_id
                  AND position >= 1
                """
            ),
            {"template_list_id": template_list_id},
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO board_template_cards (
                    template_list_id, title, description_md, position,
                    requires_credentials, requires_file_upload
                )
                VALUES (
                    :template_list_id, :title, :description_md, 1,
                    false, true
                )
                """
            ),
            {
                "template_list_id": template_list_id,
                "title": TAXES_TITLE,
                "description_md": TAXES_DESCRIPTION,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM board_cards
            WHERE title = :title
              AND requires_file_upload IS true
              AND list_id IN (
                  SELECT id FROM board_lists WHERE title = 'Client TO DO'
              )
            """
        ),
        {"title": TAXES_TITLE},
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM board_template_cards
            WHERE title = :title
              AND requires_file_upload IS true
              AND template_list_id IN (
                  SELECT id FROM board_template_lists WHERE title = 'Client TO DO'
              )
            """
        ),
        {"title": TAXES_TITLE},
    )
