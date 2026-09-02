from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.security import create_sensitive_step_up_token
from app.models.enums import DocumentType
from app.services.sensitive_documents import (
    STEP_UP_NOT_ENABLED_CODE,
    STEP_UP_REQUIRED_CODE,
    assert_sensitive_document_access,
    assert_sensitive_ssn_access,
)


def _user(*, role: str, totp_enabled: bool = True, user_id: int = 7) -> SimpleNamespace:
    role_obj = SimpleNamespace(code=role)
    return SimpleNamespace(id=user_id, role=role_obj, totp_enabled=totp_enabled)


def test_client_can_view_own_ssn_without_step_up():
    assert_sensitive_document_access(
        user=_user(role="CLIENT"),
        document_type=DocumentType.SSN_CARD.value,
        step_up_token=None,
    )


def test_client_ssn_number_requires_step_up():
    with pytest.raises(HTTPException) as exc:
        assert_sensitive_ssn_access(
            user=_user(role="CLIENT"),
            step_up_token=None,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == STEP_UP_REQUIRED_CODE


def test_client_ssn_number_requires_totp_enabled():
    with pytest.raises(HTTPException) as exc:
        assert_sensitive_ssn_access(
            user=_user(role="CLIENT", totp_enabled=False),
            step_up_token=None,
        )
    assert exc.value.detail["code"] == STEP_UP_NOT_ENABLED_CODE


def test_client_ssn_number_accepts_valid_step_up():
    token = create_sensitive_step_up_token("7")
    assert_sensitive_ssn_access(
        user=_user(role="CLIENT", user_id=7),
        step_up_token=token,
    )


def test_staff_ssn_requires_step_up_token():
    with pytest.raises(HTTPException) as exc:
        assert_sensitive_document_access(
            user=_user(role="ADVISOR"),
            document_type=DocumentType.SSN_CARD.value,
            step_up_token=None,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == STEP_UP_REQUIRED_CODE


def test_staff_ssn_requires_totp_enabled():
    with pytest.raises(HTTPException) as exc:
        assert_sensitive_document_access(
            user=_user(role="ADMIN", totp_enabled=False),
            document_type=DocumentType.SSN_CARD.value,
            step_up_token=None,
        )
    assert exc.value.detail["code"] == STEP_UP_NOT_ENABLED_CODE


def test_staff_ssn_accepts_valid_step_up():
    token = create_sensitive_step_up_token("7")
    assert_sensitive_document_access(
        user=_user(role="ADMIN", user_id=7),
        document_type=DocumentType.SSN_CARD.value,
        step_up_token=token,
    )


def test_license_requires_step_up():
    with pytest.raises(HTTPException) as exc:
        assert_sensitive_document_access(
            user=_user(role="ADVISOR"),
            document_type="DRIVERS_LICENSE_FRONT",
            step_up_token=None,
        )
    assert exc.value.detail["code"] == STEP_UP_REQUIRED_CODE


def test_utility_bill_requires_step_up():
    with pytest.raises(HTTPException) as exc:
        assert_sensitive_document_access(
            user=_user(role="ADVISOR"),
            document_type="UTILITY_BILL",
            step_up_token=None,
        )
    assert exc.value.detail["code"] == STEP_UP_REQUIRED_CODE
