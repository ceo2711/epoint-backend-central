"""Sync Kanban board columns to standard workflow lists

Revision ID: 004
Revises: 003

Historically this revision called ``sync_all_boards`` via the live ORM. That
breaks on a fresh database because later columns (e.g. ``board_cards.label``
from 035) are already on the model but not yet migrated. The real sync for
empty/prod DBs runs in 041 after the schema is complete. Existing environments
that already applied 004 are unaffected.
"""

from typing import Sequence, Union

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op: schema sync of Kanban columns/cards is handled in later revisions
    # (notably 041) once board_cards columns match the ORM.
    pass


def downgrade() -> None:
    pass
