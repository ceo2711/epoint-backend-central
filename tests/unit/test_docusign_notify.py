"""Idempotencia de notificación al completar contrato DocuSign."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.models.docusign_envelope import DocusignEnvelope
from app.models.notification import Notification
from app.models.user import User
from app.services.docusign.service import DocusignService


def _envelope_row(*, completion_notified_at=None) -> DocusignEnvelope:
    sender = User(id=7, email="vendedor@epoint.com", first_name="V", last_name="endedor", is_active=True)
    row = DocusignEnvelope(
        id=42,
        docusign_envelope_id="env-abc",
        sent_by_user_id=7,
        signer_name="Noelia Cardozo",
        signer_email="noelia@example.com",
        subject="ePoint contract — Signature required",
        status="completed",
        completion_notified_at=completion_notified_at,
    )
    row.sent_by = sender
    return row


def _mock_execute_results(*results):
    db = MagicMock()
    execute_results = []
    for result in results:
        mock_result = MagicMock()
        if isinstance(result, DocusignEnvelope):
            mock_result.scalar_one_or_none.return_value = result
        else:
            mock_result.scalar_one_or_none.return_value = result
        execute_results.append(mock_result)
    db.execute.side_effect = execute_results
    return db


class TestDocusignEnvelopeNotify:
    def test_notify_sets_completion_before_commit(self):
        locked = _envelope_row()
        db = _mock_execute_results(locked, None)
        service = DocusignService(db)
        row = _envelope_row()

        with patch.object(service.notifications, "notify", return_value=[MagicMock()]) as notify_mock:
            created = service._notify_envelope_completed(row)

        assert created is True
        assert len(service._pending_in_app_notifications) == 1
        assert locked.completion_notified_at is not None
        assert row.completion_notified_at is not None
        db.flush.assert_called()
        notify_mock.assert_called_once()
        assert notify_mock.call_args.kwargs["commit"] is False

    def test_notify_skips_when_already_marked(self):
        notified_at = datetime.now(timezone.utc)
        locked = _envelope_row(completion_notified_at=notified_at)
        db = _mock_execute_results(locked)
        service = DocusignService(db)
        row = _envelope_row()

        with patch.object(service.notifications, "notify") as notify_mock:
            created = service._notify_envelope_completed(row)

        notify_mock.assert_not_called()
        assert created is False
        assert row.completion_notified_at == notified_at

    def test_notify_skips_when_notification_already_exists(self):
        locked = _envelope_row()
        db = _mock_execute_results(locked, 99)
        service = DocusignService(db)
        row = _envelope_row()

        with patch.object(service.notifications, "notify") as notify_mock:
            created = service._notify_envelope_completed(row)

        notify_mock.assert_not_called()
        assert created is False
        assert locked.completion_notified_at is not None

    def test_commit_publishes_notifications_after_flush(self):
        db = MagicMock()
        service = DocusignService(db)
        notification = Notification(
            id=None,
            user_id=7,
            event_type="DOCUSIGN_ENVELOPE_COMPLETED",
            channel="IN_APP",
            title="Contrato firmado",
            body="Firmado",
            payload={"envelope_id": 42},
            status="SENT",
        )
        service._pending_in_app_notifications.append(notification)

        with patch("app.services.notifications.hub.notification_hub.publish_in_app") as publish_mock:
            service._commit_docusign_changes()

        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(notification)
        publish_mock.assert_called_once_with([notification])
