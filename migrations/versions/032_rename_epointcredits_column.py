"""Rename typo column Pendientes EpointCredints → EpointCredits

Revision ID: 032
Revises: 031
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "032"
down_revision: Union[str, None] = "031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TITLES = ("Pendientes EpointCredints", "Pendientes EpointCredicts")
NEW_TITLE = "Pendientes EpointCredits"


def upgrade() -> None:
    conn = op.get_bind()
    for old in OLD_TITLES:
        conn.execute(
            sa.text("UPDATE board_lists SET title = :new WHERE title = :old"),
            {"new": NEW_TITLE, "old": old},
        )
        conn.execute(
            sa.text("UPDATE board_template_lists SET title = :new WHERE title = :old"),
            {"new": NEW_TITLE, "old": old},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE board_lists SET title = :old WHERE title = :new"),
        {"new": NEW_TITLE, "old": "Pendientes EpointCredints"},
    )
    conn.execute(
        sa.text("UPDATE board_template_lists SET title = :old WHERE title = :new"),
        {"new": NEW_TITLE, "old": "Pendientes EpointCredints"},
    )
