import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.notification import Notification
from app.models.user import User
from app.services.notifications.providers import EmailProvider, InAppProvider, WhatsAppProvider

logger = logging.getLogger(__name__)

# Reglas de canal por evento (extensible)
EVENT_CHANNELS: dict[str, list[str]] = {
    "NEW_CLIENT_PENDING_REVIEW": ["IN_APP", "EMAIL"],
    "CLIENT_REJECTED": ["IN_APP", "EMAIL"],
    "CLIENT_APPROVED": ["IN_APP", "EMAIL", "WHATSAPP"],
    "DOCUMENT_REJECTED": ["IN_APP", "EMAIL", "WHATSAPP"],
    "DOCUMENT_EXPIRING_SOON": ["IN_APP", "EMAIL", "WHATSAPP"],
    "CLIENT_DATA_COMPLETE": ["IN_APP", "EMAIL"],
    "TASK_COMPLETED": ["IN_APP", "EMAIL"],
    "TASK_COMMENTED": ["IN_APP", "EMAIL"],
}


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self._providers = {
            "IN_APP": InAppProvider(),
            "EMAIL": EmailProvider(),
            "WHATSAPP": WhatsAppProvider(),
        }

    def notify(
        self,
        *,
        event_type: str,
        users: list[User],
        title: str,
        body: str,
        payload: dict[str, Any] | None = None,
        channels: list[str] | None = None,
    ) -> list[Notification]:
        active_channels = channels or EVENT_CHANNELS.get(event_type, ["IN_APP"])
        created: list[Notification] = []

        for user in users:
            for channel in active_channels:
                notification = self._dispatch(
                    user=user,
                    event_type=event_type,
                    channel=channel,
                    title=title,
                    body=body,
                    payload=payload,
                )
                if notification:
                    created.append(notification)

        self.db.commit()
        return created

    def _dispatch(
        self,
        *,
        user: User,
        event_type: str,
        channel: str,
        title: str,
        body: str,
        payload: dict[str, Any] | None,
    ) -> Notification | None:
        provider = self._providers.get(channel)
        if provider is None:
            return None

        status = "SENT"
        sent_at = datetime.now(timezone.utc)

        if channel == "IN_APP":
            notification = Notification(
                user_id=user.id,
                event_type=event_type,
                channel=channel,
                title=title,
                body=body,
                payload=payload,
                status=status,
                sent_at=sent_at,
            )
            self.db.add(notification)
            return notification

        recipient = user.email if channel == "EMAIL" else (user.phone or "")
        if not recipient:
            logger.warning("Usuario %s sin destino para canal %s", user.id, channel)
            return None

        if self.settings.notifications_dry_run:
            logger.info(
                "[DRY RUN] %s → %s: %s — %s",
                channel,
                recipient,
                title,
                body[:80],
            )
        else:
            success = provider.send(recipient, title, body, payload)
            if not success:
                status = "FAILED"

        notification = Notification(
            user_id=user.id,
            event_type=event_type,
            channel=channel,
            title=title,
            body=body,
            payload=payload,
            status=status,
            sent_at=sent_at if status == "SENT" else None,
        )
        self.db.add(notification)
        return notification
