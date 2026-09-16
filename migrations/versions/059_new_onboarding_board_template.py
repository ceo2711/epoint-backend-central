"""Actualizar template DEFAULT_ONBOARDING y aplicar el layout a todos los tableros.

Regenera el template y rearma los tableros de clientes existentes:
columnas canónicas, cards de Client TO DO / Credenciales, y vacía el resto.

Revision ID: 059
Revises: 058
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy.orm import Session

revision: str = "059"
down_revision: Union[str, None] = "058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        from app.services.board_sync import apply_canonical_layout_to_all_boards

        apply_canonical_layout_to_all_boards(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def downgrade() -> None:
    pass
