from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.models.enums import ClientStatus
from app.services.clients import ClientService


def _advisor(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, email=f"advisor{user_id}@epoint.test", role=SimpleNamespace(code="ADVISOR"))


class TestPickLeastLoadedAdvisor:
    def test_returns_none_when_no_advisors(self):
        db = MagicMock()
        db.execute.return_value.unique.return_value.scalars.return_value.all.return_value = []
        service = ClientService(db)
        assert service.pick_least_loaded_advisor() is None

    def test_prefers_advisor_with_fewer_assignments(self):
        light = _advisor(2)
        heavy = _advisor(1)
        db = MagicMock()
        advisors_result = MagicMock()
        advisors_result.unique.return_value.scalars.return_value.all.return_value = [heavy, light]
        load_result = MagicMock()
        load_result.all.return_value = [(1, 5), (2, 1)]
        db.execute.side_effect = [advisors_result, load_result]

        service = ClientService(db)
        assert service.pick_least_loaded_advisor() is light


class TestTryAutoApprovePendingClient:
    def test_skips_when_not_pending(self):
        service = ClientService(MagicMock())
        client = SimpleNamespace(id=9, status=ClientStatus.EN_CARGA_DATOS.value)
        assert service.try_auto_approve_pending_client(actor=MagicMock(), client=client) is False

    def test_skips_when_validation_fails(self):
        service = ClientService(MagicMock())
        client = SimpleNamespace(id=9, status=ClientStatus.PENDIENTE_DE_REVISION.value)
        with patch(
            "app.services.chatbot.approval_rules.validate_approval_requirements",
            return_value=["Email vacío"],
        ):
            assert service.try_auto_approve_pending_client(actor=MagicMock(), client=client) is False

    def test_approves_when_valid(self):
        service = ClientService(MagicMock())
        client = SimpleNamespace(id=9, status=ClientStatus.PENDIENTE_DE_REVISION.value)
        actor = MagicMock()
        service.approve_client = MagicMock(return_value=(client, "TempPass1!"))

        with patch(
            "app.services.chatbot.approval_rules.validate_approval_requirements",
            return_value=[],
        ):
            ok = service.try_auto_approve_pending_client(actor=actor, client=client, commit=False)

        assert ok is True
        service.approve_client.assert_called_once_with(
            actor=actor,
            client=client,
            send_welcome_notifications=True,
            commit=False,
        )
