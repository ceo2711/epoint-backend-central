"""Documentos del cliente: el staff necesita step-up de 2FA para verlos."""

from fastapi import HTTPException, status

from app.core.security import safe_decode_token
from app.models.user import User

STEP_UP_REQUIRED_CODE = "SENSITIVE_2FA_REQUIRED"
STEP_UP_NOT_ENABLED_CODE = "SENSITIVE_2FA_NOT_ENABLED"


def is_sensitive_document_type(document_type: str | None) -> bool:
    return True


def staff_requires_sensitive_step_up(user: User) -> bool:
    """El cliente puede ver sus propios archivos (mobile). El staff necesita 2FA."""
    return user.role.code != "CLIENT"


def assert_sensitive_document_access(
    *,
    user: User,
    document_type: str | None,
    step_up_token: str | None,
    require_even_for_client: bool = False,
) -> None:
    if not is_sensitive_document_type(document_type):
        return
    if not require_even_for_client and not staff_requires_sensitive_step_up(user):
        return
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": STEP_UP_NOT_ENABLED_CODE,
                "message": "Activá el doble factor de autenticación para ver este documento",
            },
        )
    payload = safe_decode_token(step_up_token or "")
    if (
        payload is None
        or payload.get("type") != "sensitive_step_up"
        or str(payload.get("sub")) != str(user.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": STEP_UP_REQUIRED_CODE,
                "message": "Ingresá el código de doble factor para ver este documento",
            },
        )


def assert_sensitive_ssn_access(*, user: User, step_up_token: str | None) -> None:
    """El número de SSN requiere step-up 2FA, también para el cliente."""
    assert_sensitive_document_access(
        user=user,
        document_type="SSN_CARD",
        step_up_token=step_up_token,
        require_even_for_client=True,
    )
