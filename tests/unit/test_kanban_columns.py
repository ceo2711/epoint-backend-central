from app.constants.kanban_columns import (
    BUSINESS_FUNDING_SEQUENCE,
    KANBAN_COLUMN_TITLES,
    PERSONAL_FUNDING_SEQUENCE,
    canonical_column_title,
    funding_sequence_title_variants,
    is_completed_column,
    is_funding_sequence_column,
    is_legacy_column_to_remove,
    is_system_kanban_column,
)


def test_funding_typo_aliases():
    assert canonical_column_title("Personal Fonding Sequence") == PERSONAL_FUNDING_SEQUENCE
    assert canonical_column_title("Business Founding Sequence (2)") == "Business Funding Sequence (2)"
    assert is_funding_sequence_column("Personal Fonding Sequence (2)") is True
    assert is_funding_sequence_column("Client TO DO") is False
    assert "Business Founding Sequence" in funding_sequence_title_variants()


def test_completed_column_alias():
    assert is_completed_column("Completed") is True
    assert is_completed_column("Client TO DO") is False


def test_system_kanban_columns():
    assert is_system_kanban_column("Experian") is True
    assert is_system_kanban_column("Credenciales") is True
    assert is_system_kanban_column(PERSONAL_FUNDING_SEQUENCE) is True
    assert is_system_kanban_column(BUSINESS_FUNDING_SEQUENCE) is True
    assert is_system_kanban_column("Completed") is False
    assert is_system_kanban_column("Pendientes EpointCredits") is False
    assert is_system_kanban_column("Cuentas de banco") is False
    assert is_system_kanban_column("Personal Funding Sequence (2)") is False
    assert is_system_kanban_column("Seguimiento extra") is False
    assert len(KANBAN_COLUMN_TITLES) == 8
    assert is_legacy_column_to_remove("Pendientes EpointCredints") is True
    assert is_legacy_column_to_remove("Cuentas de banco") is True
    assert is_legacy_column_to_remove("Personal Funding Sequence (2)") is True
    assert is_legacy_column_to_remove("Completed") is True
    assert is_legacy_column_to_remove("Client TO DO") is False
