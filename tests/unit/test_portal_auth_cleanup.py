from types import SimpleNamespace
from unittest.mock import MagicMock, call

from app.services.clients import ClientService


class TestPortalAuthCleanup:
    def test_clear_portal_auth_state_resets_2fa_and_tokens(self):
        db = MagicMock()
        service = ClientService(db)
        user = SimpleNamespace(
            id=44,
            totp_enabled=True,
            totp_secret_encrypted="secret",
            totp_confirmed_at="2026-01-01",
            must_change_password=False,
        )

        service._clear_portal_auth_state(user)

        assert user.totp_enabled is False
        assert user.totp_secret_encrypted is None
        assert user.totp_confirmed_at is None
        assert user.must_change_password is True
        assert db.execute.call_count == 2

    def test_purge_portal_user_deletes_auth_artifacts(self):
        db = MagicMock()
        service = ClientService(db)
        user = SimpleNamespace(id=55)

        service._purge_portal_user(user)

        assert db.execute.call_count == 6
        db.delete.assert_called_once_with(user)

    def test_resolve_reused_portal_user_clears_2fa(self):
        db = MagicMock()
        service = ClientService(db)
        client_role = SimpleNamespace(id=9, code="CLIENT")
        client = SimpleNamespace(
            id=10,
            email="cliente@test.com",
            first_name="Ana",
            last_name="Test",
            phone="111",
        )
        existing = SimpleNamespace(
            id=77,
            email="cliente@test.com",
            role=SimpleNamespace(code="CLIENT"),
            client_id=None,
            totp_enabled=True,
            totp_secret_encrypted="old",
            totp_confirmed_at="x",
            must_change_password=False,
            password_hash="old",
            is_active=False,
            first_name="Old",
            last_name="Name",
            phone=None,
            role_id=1,
        )
        query = MagicMock()
        query.unique.return_value.scalar_one_or_none.side_effect = [None, existing]
        db.execute.return_value = query

        service._clear_portal_auth_state = MagicMock()
        with MagicMock() as _hp:
            import app.services.clients as clients_mod

            original = clients_mod.hash_password
            clients_mod.hash_password = MagicMock(return_value="hashed")
            try:
                result = service._resolve_portal_user(client, client_role, "Temp123!")
            finally:
                clients_mod.hash_password = original

        assert result is existing
        service._clear_portal_auth_state.assert_called_once_with(existing)
        assert existing.client_id == 10
        assert existing.is_active is True
