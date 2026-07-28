"""Backfill missing default board cards (e.g. partial Client TO DO after migration 025)

Revision ID: 041
Revises: 040
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy.orm import Session

revision: str = "041"
down_revision: Union[str, None] = "040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        from app.services.board_sync import sync_all_boards

        sync_all_boards(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def downgrade() -> None:
    pass
