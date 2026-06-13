import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
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
        channel_bodies: dict[str, str] | None = None,
    ) -> list[Notification]:
        active_channels = channels or EVENT_CHANNELS.get(event_type, ["IN_APP"])
        created: list[Notification] = []

        for user in users:
            if user.id is None:
                logger.error(
                    "No se puede notificar a usuario sin id (evento %s, email %s)",
                    event_type,
                    user.email,
                )
                continue
            for channel in active_channels:
                channel_body = (channel_bodies or {}).get(channel, body)
                notification = self._dispatch(
                    user=user,
                    event_type=event_type,
                    channel=channel,
                    title=title,
                    body=channel_body,
                    payload=payload,
                )
                if notification:
                    created.append(notification)

        self.db.commit()
        return created

    def apply_in_app_scope(self, query, user: User):
        """Restringe notificaciones in-app al usuario autenticado (y a su cliente si es portal)."""
        query = query.where(
            Notification.user_id == user.id,
            Notification.channel == "IN_APP",
        )
        if user.role.code == "CLIENT" and user.client_id is not None:
            query = query.where(Notification.payload["client_id"].as_integer() == user.client_id)
        return query

    def mark_client_events_read(
        self,
        *,
        client_id: int,
        event_types: list[str],
        user_ids: list[int] | None = None,
    ) -> int:
        """Marca como leídas las notificaciones in-app pendientes de un cliente."""
        query = select(Notification).where(
            Notification.channel == "IN_APP",
            Notification.read_at.is_(None),
            Notification.event_type.in_(event_types),
        )
        if user_ids is not None:
            query = query.where(Notification.user_id.in_(user_ids))

        notifications = self.db.execute(query).scalars().all()
        now = datetime.now(timezone.utc)
        marked = 0
        for notification in notifications:
            payload = notification.payload or {}
            if payload.get("client_id") == client_id:
                notification.read_at = now
                marked += 1
        return marked

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
        if channel == "WHATSAPP" and payload and payload.get("client_phone"):
            recipient = str(payload["client_phone"])
        if not recipient:
            logger.warning("Usuario %s sin destino para canal %s", user.id, channel)
            return None

        if self.settings.notifications_dry_run:
            logger.info(
                "[DRY RUN] %s → %s: %s — %s",
                channel,
                recipient,
                title,
                body if channel in ("EMAIL", "WHATSAPP") else body[:120],
            )
        else:
            success = provider.send(recipient, title, body, payload)
            if not success:
                status = "FAILED"
                logger.warning(
                    "Notificación %s fallida para usuario %s → %s",
                    channel,
                    user.id,
                    recipient,
                )
            elif channel == "WHATSAPP":
                logger.info("Notificación WHATSAPP enviada a %s (usuario %s)", recipient, user.id)

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
