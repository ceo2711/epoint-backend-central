from unittest.mock import MagicMock

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
