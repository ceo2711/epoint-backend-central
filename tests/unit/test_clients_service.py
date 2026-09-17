from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.clients import ClientService


class TestClientServicePhoneMatching:
    def test_find_client_with_phone_matches_normalized(self):
        client = MagicMock()
        client.id = 5
        client.phone = "+5491131432490"

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [client]

        service = ClientService(db)
        found = service.find_client_with_phone("1131432490")

        assert found is client

    def test_find_client_with_phone_excludes_id(self):
        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []

        service = ClientService(db)
        found = service.find_client_with_phone("1131432490", exclude_client_id=5)

        assert found is None


class TestClientSsnDisplay:
    def test_format_ssn_display_hyphenates_nine_digits(self):
        assert ClientService.format_ssn_display("123456789") == "123-45-6789"
        assert ClientService.format_ssn_display("123-45-6789") == "123-45-6789"

    def test_get_client_ssn_raises_when_missing(self):
        client = MagicMock()
        client.ssn_encrypted = None
        service = ClientService(MagicMock())
        with pytest.raises(HTTPException) as exc:
            service.get_client_ssn(client)
        assert exc.value.status_code == 404
