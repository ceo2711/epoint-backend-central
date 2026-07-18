"""users.client_id ON DELETE SET NULL

Revision ID: 026
Revises: 025
"""

from typing import Sequence, Union

from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("fk_users_client_id", "users", type_="foreignkey")
    op.create_foreign_key(
        "fk_users_client_id",
        "users",
        "clients",
        ["client_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_client_id", "users", type_="foreignkey")
    op.create_foreign_key(
        "fk_users_client_id",
        "users",
        "clients",
        ["client_id"],
        ["id"],
    )
