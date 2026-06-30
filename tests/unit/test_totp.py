import pytest

from app.services.totp import (
    build_provisioning_uri,
    generate_totp_secret,
    verify_totp_code,
)
import pyotp


def test_generate_totp_secret_length():
    secret = generate_totp_secret()
    assert len(secret) >= 16


def test_build_provisioning_uri_contains_email():
    secret = generate_totp_secret()
    uri = build_provisioning_uri(email="user@test.com", secret=secret)
    assert "user%40test.com" in uri or "user@test.com" in uri
    assert "otpauth://" in uri


def test_verify_totp_code_accepts_valid_code():
    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp_code(secret=secret, code=code) is True


def test_verify_totp_code_rejects_invalid_code():
    secret = generate_totp_secret()
    assert verify_totp_code(secret=secret, code="000000") is False
