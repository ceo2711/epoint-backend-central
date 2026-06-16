from datetime import date

import pytest
from pydantic import ValidationError

from app.core.validation_errors import humanize_validation_error, humanize_validation_errors
from app.schemas.client import ProfileUpdate


class TestProfileUpdate:
    def test_empty_ssn_is_ignored(self):
        profile = ProfileUpdate(ssn="", date_of_birth=date(1996, 1, 16))
        assert profile.ssn is None
        assert profile.date_of_birth == date(1996, 1, 16)

    def test_ssn_with_dashes_is_normalized(self):
        profile = ProfileUpdate(ssn="123-45-6789")
        assert profile.ssn == "123456789"

    def test_invalid_ssn_length(self):
        with pytest.raises(ValidationError) as exc:
            ProfileUpdate(ssn="12345")
        assert "9 dígitos" in str(exc.value)


class TestValidationErrors:
    def test_humanize_ssn_too_short(self):
        message = humanize_validation_error(
            {
                "type": "string_too_short",
                "loc": ("body", "ssn"),
                "msg": "String should have at least 9 characters",
                "ctx": {"min_length": 9},
            }
        )
        assert message == "El número de Seguro Social debe tener 9 dígitos (formato XXX-XX-XXXX)."

    def test_humanize_value_error(self):
        message = humanize_validation_error(
            {
                "type": "value_error",
                "loc": ("body", "ssn"),
                "msg": "Value error, El número de Seguro Social debe tener 9 dígitos (formato XXX-XX-XXXX).",
            }
        )
        assert message == "El número de Seguro Social debe tener 9 dígitos (formato XXX-XX-XXXX)."

    def test_humanize_multiple_errors(self):
        message = humanize_validation_errors(
            [
                {
                    "type": "string_too_short",
                    "loc": ("body", "password"),
                    "msg": "String should have at least 8 characters",
                    "ctx": {"min_length": 8},
                },
                {
                    "type": "value_error.email",
                    "loc": ("body", "email"),
                    "msg": "value is not a valid email address",
                },
            ]
        )
        assert "contraseña" in message.lower()
        assert "correo" in message.lower()
