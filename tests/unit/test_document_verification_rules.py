from app.services.document_verification_rules import (
    build_document_type_context,
    is_verification_approved,
)


def _quality_pass_result(**overrides):
    base = {
        "is_readable": True,
        "is_complete": True,
        "is_color": True,
        "corners_cut": False,
        "is_expired": False,
        "document_type_matches": True,
        "detected_document_type": "SSN card",
        "name_matches": True,
        "address_matches": False,
    }
    base.update(overrides)
    return base


def test_ssn_rejected_when_wrong_document_type_flag_false():
    result = _quality_pass_result(document_type_matches=False, detected_document_type="invoice")
    assert is_verification_approved(result, "SSN_CARD") is False


def test_ssn_rejected_when_name_missing():
    result = _quality_pass_result(name_matches=False)
    assert is_verification_approved(result, "SSN_CARD") is False


def test_ssn_rejected_when_detected_type_conflicts():
    result = _quality_pass_result(
        document_type_matches=True,
        detected_document_type="Stripe executive report",
    )
    assert is_verification_approved(result, "SSN_CARD") is False


def test_ssn_approved_only_with_all_required_flags():
    result = _quality_pass_result()
    assert is_verification_approved(result, "SSN_CARD") is True


def test_missing_document_type_matches_fails_closed():
    result = _quality_pass_result()
    del result["document_type_matches"]
    assert is_verification_approved(result, "SSN_CARD") is False


def test_license_back_approved_without_name_match():
    result = _quality_pass_result(
        detected_document_type="driver license back",
        name_matches=False,
    )
    assert is_verification_approved(result, "DRIVERS_LICENSE_BACK") is True


def test_license_front_rejected_when_name_missing():
    result = _quality_pass_result(
        detected_document_type="driver license front",
        name_matches=False,
    )
    assert is_verification_approved(result, "DRIVERS_LICENSE_FRONT") is False


def test_build_document_type_context_includes_expected_type():
    context = build_document_type_context("SSN_CARD", "Alexis Guanique")
    assert "SSN_CARD" in context
    assert "Alexis Guanique" in context
    assert "Social Security" in context
