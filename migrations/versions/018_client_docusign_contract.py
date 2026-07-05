"""Cliente: contrato DocuSign firmado."""

from alembic import op
import sqlalchemy as sa

revision = "018_client_docusign_contract"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("docusign_contract_signed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "clients",
        sa.Column("docusign_envelope_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_clients_docusign_envelope_id",
        "clients",
        "docusign_envelopes",
        ["docusign_envelope_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_clients_docusign_envelope_id"),
        "clients",
        ["docusign_envelope_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_clients_docusign_envelope_id"), table_name="clients")
    op.drop_constraint("fk_clients_docusign_envelope_id", "clients", type_="foreignkey")
    op.drop_column("clients", "docusign_envelope_id")
    op.drop_column("clients", "docusign_contract_signed_at")
