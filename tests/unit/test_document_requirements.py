from app.services.document_requirements import (
    ADDRESS_GAP_KEY,
    BANK_STATEMENT,
    IDENTITY_GAP_KEY,
    LICENSE_BACK,
    LICENSE_FRONT,
    PASSPORT,
    SSN_CARD,
    UTILITY_BILL,
    all_required_documents_approved,
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
