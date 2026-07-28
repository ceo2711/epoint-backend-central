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


def test_license_back_approved_when_background_doc_mentioned():
    """No rechazar dorso válido solo porque Gemini menciona otro papel detrás."""
    result = _quality_pass_result(
        detected_document_type="driver license back with ssn card underneath",
        name_matches=False,
    )
    assert is_verification_approved(result, "DRIVERS_LICENSE_BACK") is True


def test_license_back_still_rejected_when_primary_is_ssn():
    result = _quality_pass_result(
        detected_document_type="ssn card",
        name_matches=False,
    )
    assert is_verification_approved(result, "DRIVERS_LICENSE_BACK") is False


def test_license_back_ignores_expired_hallucination():
    """El dorso no usa is_expired; ignorar alucinaciones de vencimiento."""
    result = _quality_pass_result(
        detected_document_type="driver license back",
        name_matches=False,
        is_expired=True,
        expires_at="2020-01-01",
    )
    assert is_verification_approved(result, "DRIVERS_LICENSE_BACK") is True


def test_license_front_rejected_when_name_missing():
    result = _quality_pass_result(
        detected_document_type="driver license front",
        name_matches=False,
    )
    assert is_verification_approved(result, "DRIVERS_LICENSE_FRONT") is False


def test_ssn_approved_even_if_ai_marks_expired():
    """Las tarjetas SSN no vencen; ignorar alucinaciones de is_expired."""
    result = _quality_pass_result(
        is_expired=True,
        expires_at="2024-03-01",
        rejection_reasons=[
            {"en": "Expired", "es": "Vencido"},
        ],
    )
    assert is_verification_approved(result, "SSN_CARD") is True


def test_license_still_rejected_when_expired():
    result = _quality_pass_result(
        detected_document_type="driver license front",
        is_expired=True,
        expires_at="2024-03-01",
    )
    assert is_verification_approved(result, "DRIVERS_LICENSE_FRONT") is False


def test_utility_bill_ignores_expired_flag():
    result = _quality_pass_result(
        detected_document_type="Electric Utility Bill",
        is_expired=True,
        name_matches=True,
        address_matches=True,
    )
    assert is_verification_approved(result, "UTILITY_BILL") is True


def test_utility_bill_soft_name_match_ocr_typo():
    result = _quality_pass_result(
        detected_document_type="Electric Utility Bill",
        name_matches=False,
        address_matches=True,
        detected_name="Eliangli L Viamonte Rivas",
        rejection_reasons=[
            {
                "en": "The customer name on the document ('Eliangli L Viamonte Rivas') does not match.",
                "es": "El nombre no coincide.",
            }
        ],
    )
    assert (
        is_verification_approved(
            result,
            "UTILITY_BILL",
            client_name="Eliangi Liduvina Viamonte Rivas",
        )
        is True
    )


def test_soft_quality_flags_do_not_block_approval():
    """Esquinas/color/complete no deben tumbar un doc del tipo correcto y legible."""
    result = _quality_pass_result(
        is_complete=False,
        is_color=False,
        corners_cut=True,
        address_matches=False,
        detected_document_type="Electric Utility Bill",
        name_matches=True,
    )
    assert is_verification_approved(result, "UTILITY_BILL") is True


def test_utility_bill_approved_without_strict_address_flag():
    result = _quality_pass_result(
        detected_document_type="utility bill",
        name_matches=True,
        address_matches=False,
    )
    assert is_verification_approved(result, "UTILITY_BILL") is True


def test_build_document_type_context_includes_expected_type():
    context = build_document_type_context("SSN_CARD", "Alexis Guanique")
    assert "SSN_CARD" in context
    assert "Alexis Guanique" in context
    assert "Social Security" in context
    assert "do NOT expire" in context or "never expire" in context
    assert "Today's date" in context
