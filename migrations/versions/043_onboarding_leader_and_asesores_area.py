"""Replace ONBOARDING_MANAGER with AREA_LEADER+ONBOARDING; add ASESORES area

Revision ID: 043
Revises: 042
"""

from typing import Sequence, Union

from alembic import op

revision: str = "043"
down_revision: Union[str, None] = "042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Área de asesores (separada de onboarding)
    op.execute(
        """
        INSERT INTO areas (code, name, description, is_active)
        SELECT 'ASESORES', 'Asesores', 'Equipo de acompañamiento de clientes', TRUE
        WHERE NOT EXISTS (SELECT 1 FROM areas WHERE code = 'ASESORES')
        """
    )

    # Asesores pasan al área ASESORES
    op.execute(
        """
        UPDATE users
        SET area_id = (SELECT id FROM areas WHERE code = 'ASESORES')
        WHERE role_id = (SELECT id FROM roles WHERE code = 'ADVISOR')
        """
    )

    # system@ deja de ser "encargado": autor técnico de comentarios del tablero
    op.execute(
        """
        UPDATE users
        SET
          role_id = (SELECT id FROM roles WHERE code = 'ADVISOR'),
          area_id = (SELECT id FROM areas WHERE code = 'ASESORES')
        WHERE email = 'system@epoint.com'
          AND role_id = (SELECT id FROM roles WHERE code = 'ONBOARDING_MANAGER')
        """
    )

    # Un líder de onboarding por sede: el OM activo más antiguo (preferir onboarding@)
    op.execute(
        """
        WITH ranked AS (
          SELECT
            u.id,
            u.sede_id,
            ROW_NUMBER() OVER (
              PARTITION BY u.sede_id
              ORDER BY
                CASE WHEN u.email = 'onboarding@epoint.com' THEN 0 ELSE 1 END,
                u.id
            ) AS rn
          FROM users u
          JOIN roles r ON r.id = u.role_id
          WHERE r.code = 'ONBOARDING_MANAGER'
            AND u.is_active IS TRUE
        )
        UPDATE users u
        SET
          role_id = (SELECT id FROM roles WHERE code = 'AREA_LEADER'),
          area_id = (SELECT id FROM areas WHERE code = 'ONBOARDING')
        FROM ranked
        WHERE u.id = ranked.id
          AND ranked.rn = 1
        """
    )

    # OM restantes (duplicados u otros): desactivar para no violar unicidad de líder
    op.execute(
        """
        UPDATE users
        SET is_active = FALSE
        WHERE role_id = (SELECT id FROM roles WHERE code = 'ONBOARDING_MANAGER')
          AND is_active IS TRUE
        """
    )

    # Deprecar rol Encargado de Onboarding (ya no asignable)
    op.execute(
        """
        UPDATE roles
        SET
          is_active = FALSE,
          name = 'Encargado de Onboarding (deprecado)',
          description = 'Reemplazado por Líder de área + área Onboarding'
        WHERE code = 'ONBOARDING_MANAGER'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET
          is_active = TRUE,
          name = 'Encargado de Onboarding',
          description = 'Revisa y aprueba clientes, gestiona onboarding'
        WHERE code = 'ONBOARDING_MANAGER'
        """
    )
    # No revertimos usuarios automáticamente (pérdida de información ambigua).
