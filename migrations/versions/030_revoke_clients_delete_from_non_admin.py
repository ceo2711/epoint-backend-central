"""Revoke clients:delete from non-ADMIN roles

Revision ID: 030
Revises: 029
"""

from typing import Sequence, Union

from alembic import op

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id = (SELECT id FROM permissions WHERE code = 'clients:delete')
          AND role_id IN (SELECT id FROM roles WHERE code <> 'ADMIN')
        """
    )


def downgrade() -> None:
    # No reasignamos clients:delete a gerentes u otros roles en downgrade.
    pass
