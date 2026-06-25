from app.services.board_attachment_verification_rules import (
    CLARITY_REPORT,
    CREDIT_BUREAU_REPORTS,
    EQUIFAX_CREDIT_REPORT,
    EXPERIAN_CREDIT_REPORT,
    TRANSUNION_CREDIT_REPORT,
    build_board_attachment_context,
    is_board_attachment_approved,
    resolve_attachment_kind,
)


def test_resolve_credit_bureau_reports_card():
    kind = resolve_attachment_kind(
        card_title="Reportes: Experian, Equifax y TransUnion",
        list_title="Client TO DO",
        requires_file_upload=True,
    )
    assert kind == CREDIT_BUREAU_REPORTS


def test_resolve_equifax_column():
    kind = resolve_attachment_kind(
        card_title="Accounts",
        list_title="Equifax",
        requires_file_upload=False,
    )
    assert kind == EQUIFAX_CREDIT_REPORT


def test_resolve_experian_column():
    kind = resolve_attachment_kind(
        card_title="Accounts",
        list_title="Experian",
        requires_file_upload=False,
    )
    assert kind == EXPERIAN_CREDIT_REPORT


def test_resolve_transunion_column():
    kind = resolve_attachment_kind(
        card_title="Accounts",
        list_title="Transunion",
        requires_file_upload=False,
    )
    assert kind == TRANSUNION_CREDIT_REPORT


def test_resolve_clarity_card():
    kind = resolve_attachment_kind(
        card_title="Clarity Services",
        list_title="Credenciales",
        requires_file_upload=True,
    )
    assert kind == CLARITY_REPORT


def test_build_context_includes_client_name():
    context = build_board_attachment_context(
        attachment_kind=EQUIFAX_CREDIT_REPORT,
        client_name="Jane Doe",
        card_title="Accounts",
        list_title="Equifax",
    )
    assert "Jane Doe" in context
    assert "EQUIFAX_CREDIT_REPORT" in context
    assert "Equifax" in context


def test_approve_equifax_report():
    result = {
        "is_readable": True,
        "is_complete": True,
        "is_recent": True,
        "document_type_matches": True,
        "detected_bureau": "Equifax",
        "name_matches": True,
    }
    assert is_board_attachment_approved(result, EQUIFAX_CREDIT_REPORT) is True


def test_reject_wrong_bureau_for_equifax():
    result = {
        "is_readable": True,
        "is_complete": True,
        "is_recent": True,
        "document_type_matches": True,
        "detected_bureau": "Experian",
        "name_matches": True,
    }
    assert is_board_attachment_approved(result, EQUIFAX_CREDIT_REPORT) is False


def test_approve_any_bureau_for_combined_reports_card():
    result = {
        "is_readable": True,
        "is_complete": True,
        "is_recent": True,
        "document_type_matches": True,
        "detected_bureau": "TransUnion",
        "name_matches": True,
    }
    assert is_board_attachment_approved(result, CREDIT_BUREAU_REPORTS) is True


def test_reject_missing_name():
    result = {
        "is_readable": True,
        "is_complete": True,
        "is_recent": True,
        "document_type_matches": True,
        "detected_bureau": "Equifax",
        "name_matches": False,
    }
    assert is_board_attachment_approved(result, EQUIFAX_CREDIT_REPORT) is False
