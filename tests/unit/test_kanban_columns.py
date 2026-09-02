from app.constants.kanban_columns import (
    BUSINESS_FUNDING_SEQUENCE,
    PERSONAL_FUNDING_SEQUENCE,
    canonical_column_title,
    funding_sequence_title_variants,
    is_completed_column,
    is_funding_sequence_column,
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
