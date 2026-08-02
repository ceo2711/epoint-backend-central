"""Add SUB_SELLER role and migrate parented sales users

Revision ID: 042
Revises: 041
"""

from typing import Sequence, Union

from alembic import op

revision: str = "042"
down_revision: Union[str, None] = "041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SUB_SELLER_PERMISSIONS = (
    "clients:read",
    "clients:create",
    "clients:update",
    "prospects:read",
    "prospects:create",
    "prospects:update",
    "calendly:read",
    "calendly:manage",
    "payments:read",
    "payments:create",
)


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO roles (code, name, description, is_active)
        SELECT 'SUB_SELLER', 'Subvendedor',
               'Vendedor bajo la supervisión de un vendedor titular', TRUE
        WHERE NOT EXISTS (SELECT 1 FROM roles WHERE code = 'SUB_SELLER')
        """
    )
    for code in SUB_SELLER_PERMISSIONS:
        op.execute(
            f"""
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.code = 'SUB_SELLER'
              AND p.code = '{code}'
              AND NOT EXISTS (
                SELECT 1 FROM role_permissions rp
                WHERE rp.role_id = r.id AND rp.permission_id = p.id
              )
            """
        )
    # Usuarios que ya eran subvendedores vía parent_user_id
    op.execute(
        """
        UPDATE users
        SET role_id = (SELECT id FROM roles WHERE code = 'SUB_SELLER')
        WHERE parent_user_id IS NOT NULL
          AND role_id = (SELECT id FROM roles WHERE code = 'SALES_REP')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE users
        SET role_id = (SELECT id FROM roles WHERE code = 'SALES_REP')
        WHERE role_id = (SELECT id FROM roles WHERE code = 'SUB_SELLER')
        """
    )
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE role_id = (SELECT id FROM roles WHERE code = 'SUB_SELLER')
        """
    )
    op.execute("DELETE FROM roles WHERE code = 'SUB_SELLER'")
