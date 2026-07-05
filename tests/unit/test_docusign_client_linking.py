from app.models.client import Client
from app.services.docusign.service import DocusignService


def _client(first: str, last: str, email: str) -> Client:
    return Client(
        id=1,
        first_name=first,
        last_name=last,
        email=email,
        phone="+5491111111111",
        registered_by_user_id=1,
    )


class TestDocusignClientLinking:
    def test_resolve_sent_by_user_id_onboarding_uses_registered_by(self):
        from unittest.mock import MagicMock

        client = _client("Juan", "Pérez", "juan@example.com")
        client.registered_by_user_id = 42

        onboarding = MagicMock()
        onboarding.id = 9
        onboarding.role.code = "ONBOARDING_MANAGER"

        assert DocusignService._resolve_sent_by_user_id(onboarding, client) == 42

    def test_resolve_sent_by_user_id_sales_rep_uses_actor(self):
        from unittest.mock import MagicMock

        client = _client("Juan", "Pérez", "juan@example.com")
        client.registered_by_user_id = 42

        sales_rep = MagicMock()
        sales_rep.id = 7
        sales_rep.role.code = "SALES_REP"

        assert DocusignService._resolve_sent_by_user_id(sales_rep, client) == 7

    def test_parse_signer_name(self):
        first, last = DocusignService._parse_signer_name("Alexis Antonio Guanique Diaz")
        assert first == "Alexis"
        assert last == "Antonio Guanique Diaz"

    def test_client_matches_signer_by_full_name(self):
        client = _client("Alexis", "Guanique", "test@example.com")
        assert DocusignService._client_matches_signer(client, "Alexis Guanique", "test@example.com")

    def test_client_does_not_match_different_name_same_email(self):
        client = _client("Angela", "Silva Paez", "guaniqued@gmail.com")
        assert not DocusignService._client_matches_signer(
            client,
            "Alexis Guanique",
            "guaniqued@gmail.com",
        )
