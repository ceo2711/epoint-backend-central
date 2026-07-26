from app.services.document_requirements import (
    ADDRESS_GAP_KEY,
    BANK_STATEMENT,
    GREEN_CARD,
    IDENTITY_GAP_KEY,
    LICENSE_BACK,
    LICENSE_FRONT,
    PASSPORT,
    SSN_CARD,
    UTILITY_BILL,
    all_required_documents_approved,
    document_needs_client_action,
    document_reminder_gaps,
    document_upload_gaps,
    is_upload_requirement_met,
    resolve_required_upload_types,
)


def test_license_path_complete():
    uploaded = {SSN_CARD, LICENSE_FRONT, LICENSE_BACK, UTILITY_BILL}
    assert is_upload_requirement_met(uploaded)
    assert resolve_required_upload_types(uploaded) == {
        SSN_CARD,
        LICENSE_FRONT,
        LICENSE_BACK,
        UTILITY_BILL,
    }


def test_passport_instead_of_license():
    uploaded = {SSN_CARD, PASSPORT, BANK_STATEMENT}
    assert is_upload_requirement_met(uploaded)
    assert resolve_required_upload_types(uploaded) == {SSN_CARD, PASSPORT, BANK_STATEMENT}


def test_bank_statement_instead_of_utility():
    uploaded = {SSN_CARD, LICENSE_FRONT, LICENSE_BACK, BANK_STATEMENT}
    assert UTILITY_BILL not in resolve_required_upload_types(uploaded)


def test_incomplete_license_only_front():
    uploaded = {SSN_CARD, LICENSE_FRONT, UTILITY_BILL}
    assert not is_upload_requirement_met(uploaded)
    assert LICENSE_BACK in document_upload_gaps(uploaded)


def test_missing_identity_shows_group_gap():
    uploaded = {SSN_CARD, UTILITY_BILL}
    assert IDENTITY_GAP_KEY in document_upload_gaps(uploaded)


def test_missing_address_shows_group_gap():
    uploaded = {SSN_CARD, LICENSE_FRONT, LICENSE_BACK}
    assert ADDRESS_GAP_KEY in document_upload_gaps(uploaded)


def test_approval_only_for_active_required_set():
    from types import SimpleNamespace

    docs = [
        SimpleNamespace(type=SSN_CARD, verification_status="APROBADO"),
        SimpleNamespace(type=PASSPORT, verification_status="APROBADO"),
        SimpleNamespace(type=BANK_STATEMENT, verification_status="APROBADO"),
        SimpleNamespace(type=UTILITY_BILL, verification_status="PENDIENTE"),
    ]
    assert all_required_documents_approved(docs) is True


def _doc(doc_type: str, status: str):
    from types import SimpleNamespace

    return SimpleNamespace(type=doc_type, verification_status=status)


def test_reminder_gaps_ignore_rejected_license_when_passport_pending():
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(LICENSE_FRONT, "RECHAZADO"),
        _doc(LICENSE_BACK, "RECHAZADO"),
        _doc(PASSPORT, "PENDIENTE"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    missing, rejected, expiring = document_reminder_gaps(docs)
    assert missing == []
    assert rejected == []
    assert expiring == []


def test_reminder_gaps_ignore_rejected_license_when_passport_approved():
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(LICENSE_FRONT, "RECHAZADO"),
        _doc(LICENSE_BACK, "RECHAZADO"),
        _doc(PASSPORT, "APROBADO"),
        _doc(BANK_STATEMENT, "APROBADO"),
    ]
    missing, rejected, expiring = document_reminder_gaps(docs)
    assert missing == []
    assert rejected == []
    assert expiring == []


def test_reminder_gaps_ignore_pending_utility_when_bank_approved():
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(PASSPORT, "APROBADO"),
        _doc(UTILITY_BILL, "PENDIENTE"),
        _doc(BANK_STATEMENT, "APROBADO"),
    ]
    missing, rejected, expiring = document_reminder_gaps(docs)
    assert missing == []
    assert rejected == []
    assert expiring == []


def test_reminder_gaps_show_identity_group_when_license_rejected_without_alternative():
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(LICENSE_FRONT, "RECHAZADO"),
        _doc(LICENSE_BACK, "RECHAZADO"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    missing, rejected, expiring = document_reminder_gaps(docs)
    assert missing == [IDENTITY_GAP_KEY]
    assert rejected == []
    assert expiring == []


def test_reminder_gaps_show_rejected_passport_when_only_identity_upload():
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(PASSPORT, "RECHAZADO"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    missing, rejected, expiring = document_reminder_gaps(docs)
    assert missing == []
    assert rejected == [PASSPORT]
    assert expiring == []


def test_reminder_gaps_show_missing_license_back_when_front_pending():
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(LICENSE_FRONT, "PENDIENTE"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    missing, rejected, expiring = document_reminder_gaps(docs)
    assert missing == [LICENSE_BACK]
    assert rejected == []
    assert expiring == []


def test_reminder_gaps_show_identity_group_when_license_front_rejected_and_back_missing():
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(LICENSE_FRONT, "RECHAZADO"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    missing, rejected, expiring = document_reminder_gaps(docs)
    assert missing == [IDENTITY_GAP_KEY]
    assert rejected == []
    assert expiring == []


def test_expiring_document_blocks_ready_to_work():
    """Un documento por vencer no habilita el pase a LISTO_PARA_TRABAJAR."""
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(LICENSE_FRONT, "PROXIMO_A_VENCER"),
        _doc(LICENSE_BACK, "APROBADO"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    assert all_required_documents_approved(docs) is False


def test_expiring_document_is_reported_as_pending():
    """Si bloquea, el cliente tiene que verlo en sus pendientes para poder resubirlo."""
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(LICENSE_FRONT, "PROXIMO_A_VENCER"),
        _doc(LICENSE_BACK, "APROBADO"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    missing, rejected, expiring = document_reminder_gaps(docs)
    assert missing == []
    assert rejected == []
    assert expiring == [LICENSE_FRONT]


def test_expiring_ssn_is_reported_as_pending():
    docs = [
        _doc(SSN_CARD, "PROXIMO_A_VENCER"),
        _doc(PASSPORT, "APROBADO"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    missing, rejected, expiring = document_reminder_gaps(docs)
    assert expiring == [SSN_CARD]


def test_expiring_license_ignored_when_passport_approved():
    """Con una alternativa aprobada, la licencia por vencer no es un pendiente."""
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(LICENSE_FRONT, "PROXIMO_A_VENCER"),
        _doc(LICENSE_BACK, "APROBADO"),
        _doc(PASSPORT, "APROBADO"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    missing, rejected, expiring = document_reminder_gaps(docs)
    assert missing == []
    assert rejected == []
    assert expiring == []
    assert all_required_documents_approved(docs) is True


def test_reminder_gaps_ignore_rejected_green_card_when_license_approved():
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(LICENSE_FRONT, "APROBADO"),
        _doc(LICENSE_BACK, "APROBADO"),
        _doc(GREEN_CARD, "RECHAZADO"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    missing, rejected, expiring = document_reminder_gaps(docs)
    assert missing == []
    assert rejected == []
    assert expiring == []


def test_rejected_green_card_needs_no_action_when_license_approved():
    """No se avisa por una alternativa rechazada si otra ya cubre la categoría."""
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(LICENSE_FRONT, "APROBADO"),
        _doc(LICENSE_BACK, "APROBADO"),
        _doc(GREEN_CARD, "RECHAZADO"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    assert document_needs_client_action(docs, GREEN_CARD) is False


def test_rejected_green_card_needs_action_without_alternative():
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(GREEN_CARD, "RECHAZADO"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    assert document_needs_client_action(docs, GREEN_CARD) is True


def test_rejected_license_needs_action_when_alternative_also_rejected():
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(LICENSE_FRONT, "RECHAZADO"),
        _doc(LICENSE_BACK, "APROBADO"),
        _doc(GREEN_CARD, "RECHAZADO"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    assert document_needs_client_action(docs, LICENSE_FRONT) is True


def test_rejected_bank_statement_needs_no_action_when_utility_approved():
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(PASSPORT, "APROBADO"),
        _doc(UTILITY_BILL, "APROBADO"),
        _doc(BANK_STATEMENT, "RECHAZADO"),
    ]
    assert document_needs_client_action(docs, BANK_STATEMENT) is False


def test_rejected_ssn_always_needs_action():
    docs = [
        _doc(SSN_CARD, "RECHAZADO"),
        _doc(PASSPORT, "APROBADO"),
        _doc(UTILITY_BILL, "APROBADO"),
    ]
    assert document_needs_client_action(docs, SSN_CARD) is True


def test_expiring_address_proof_is_reported_as_pending():
    docs = [
        _doc(SSN_CARD, "APROBADO"),
        _doc(PASSPORT, "APROBADO"),
        _doc(UTILITY_BILL, "PROXIMO_A_VENCER"),
    ]
    missing, rejected, expiring = document_reminder_gaps(docs)
    assert expiring == [UTILITY_BILL]
    assert all_required_documents_approved(docs) is False
