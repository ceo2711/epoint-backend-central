from datetime import date

from app.services.board_attachment_verification_rules import (
    CLARITY_REPORT,
    CREDIT_BUREAU_REPORTS,
    EQUIFAX_CREDIT_REPORT,
    EXPERIAN_CREDIT_REPORT,
    TAX_REPORT,
    TRANSUNION_CREDIT_REPORT,
    apply_report_date_freshness,
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
    assert "15 days" in context
    assert "Today's date" in context


def test_build_context_credit_bureau_reports_requires_fresh_report():
    context = build_board_attachment_context(
        attachment_kind=CREDIT_BUREAU_REPORTS,
        client_name="Jane Doe",
        card_title="Reportes: Experian, Equifax y TransUnion",
        list_title="Client TO DO",
    )
    assert "15 days" in context
    assert "newly generated" in context.lower() or "re-download" in context.lower()


def test_resolve_taxes_card():
    kind = resolve_attachment_kind(
        card_title="Informe de Taxes",
        list_title="Client TO DO",
        requires_file_upload=True,
    )
    assert kind == TAX_REPORT


def test_approve_tax_report():
    result = {
        "is_readable": True,
        "is_complete": True,
        "is_recent": True,
        "document_type_matches": True,
        "detected_document_type": "Form 1040 Tax Return",
        "name_matches": True,
    }
    assert is_board_attachment_approved(result, TAX_REPORT) is True


def test_reject_tax_report_wrong_document():
    result = {
        "is_readable": True,
        "is_complete": True,
        "is_recent": True,
        "document_type_matches": False,
        "detected_document_type": "Equifax credit report",
        "name_matches": True,
    }
    assert is_board_attachment_approved(result, TAX_REPORT) is False


def test_reject_outdated_report():
    result = {
        "is_readable": True,
        "is_complete": True,
        "is_recent": False,
        "report_date": "2026-01-01",
        "document_type_matches": True,
        "detected_bureau": "Equifax",
        "name_matches": True,
    }
    assert is_board_attachment_approved(result, CREDIT_BUREAU_REPORTS) is False


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


def test_context_includes_today_and_does_not_treat_today_as_future():
    today = date(2026, 8, 26)
    context = build_board_attachment_context(
        attachment_kind=CREDIT_BUREAU_REPORTS,
        client_name="Karol Nieto",
        card_title="Reportes: Experian, Equifax y TransUnion",
        list_title="Client TO DO",
        today=today,
    )
    assert "2026-08-26" in context
    assert "including Today's date" in context or "dated today is recent" in context


def test_today_report_date_is_recent():
    result = {
        "is_recent": False,
        "report_date": "2026-08-26",
        "rejection_reasons": [
            {"en": "The report date is in the future", "es": "La fecha del informe está en el futuro"}
        ],
    }
    apply_report_date_freshness(result, date(2026, 8, 26))
    assert result["is_recent"] is True
    assert result["rejection_reasons"] == []


def test_old_report_date_is_not_recent():
    result = {"is_recent": True, "report_date": "2026-01-01"}
    apply_report_date_freshness(result, date(2026, 8, 26))
    assert result["is_recent"] is False
