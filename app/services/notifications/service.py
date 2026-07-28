import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.notification import Notification
from app.models.push_device_token import PushDeviceToken
from app.models.user import User
from app.services.notifications.providers import (
    EmailProvider,
    ExpoPushProvider,
    InAppProvider,
    WhatsAppProvider,
)

logger = logging.getLogger(__name__)

# Reglas de canal por evento (extensible)
EVENT_CHANNELS: dict[str, list[str]] = {
    "NEW_CLIENT_PENDING_REVIEW": ["IN_APP", "EMAIL"],
    "CLIENT_REJECTED": ["IN_APP", "EMAIL"],
    "CLIENT_APPROVED": ["IN_APP", "PUSH"],
    "DOCUMENT_REJECTED": ["IN_APP", "EMAIL", "WHATSAPP", "PUSH"],
    "DOCUMENT_EXPIRING_SOON": ["IN_APP", "EMAIL", "WHATSAPP", "PUSH"],
    "BOARD_ATTACHMENT_REJECTED": ["IN_APP", "EMAIL", "PUSH"],
    "CLIENT_DATA_COMPLETE": ["IN_APP", "EMAIL"],
    "CLIENT_ONBOARDING_INCOMPLETE": ["IN_APP", "EMAIL", "WHATSAPP"],
    "TASK_COMPLETED": ["IN_APP", "EMAIL", "PUSH"],
    "TASK_COMMENTED": ["IN_APP", "EMAIL", "PUSH"],
    "CALENDLY_EVENT_SCHEDULED": ["IN_APP"],
    "DOCUSIGN_ENVELOPE_COMPLETED": ["IN_APP"],
    "PAYMENT_LINK_COMPLETED": ["IN_APP", "EMAIL", "PUSH"],
    "PROSPECT_CONVERTED": ["IN_APP", "EMAIL", "PUSH"],
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
        self._push = ExpoPushProvider()

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
        commit: bool = True,
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
                if channel == "PUSH":
                    self._send_push(
                        user=user,
                        title=title,
                        body=(channel_bodies or {}).get(channel, body),
                        payload=payload,
                    )
                    continue
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

        if commit:
            self.db.commit()
            from app.services.notifications.hub import notification_hub

            notification_hub.publish_in_app(created)
        else:
            self.db.flush()
        return created

    def register_device_token(self, *, user_id: int, token: str, platform: str) -> PushDeviceToken:
        normalized = token.strip()
        platform_norm = platform.strip().lower()
        existing = self.db.execute(
            select(PushDeviceToken).where(PushDeviceToken.token == normalized)
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if existing:
            existing.user_id = user_id
            existing.platform = platform_norm
            existing.updated_at = now
            existing.last_seen_at = now
            self.db.commit()
            self.db.refresh(existing)
            return existing

        row = PushDeviceToken(
            user_id=user_id,
            token=normalized,
            platform=platform_norm,
            last_seen_at=now,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def unregister_device_token(self, *, user_id: int, token: str) -> int:
        rows = (
            self.db.execute(
                select(PushDeviceToken).where(
                    PushDeviceToken.user_id == user_id,
                    PushDeviceToken.token == token.strip(),
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            self.db.delete(row)
        self.db.commit()
        return len(rows)

    def _send_push(
        self,
        *,
        user: User,
        title: str,
        body: str,
        payload: dict[str, Any] | None,
    ) -> None:
        tokens = (
            self.db.execute(
                select(PushDeviceToken.token).where(PushDeviceToken.user_id == user.id)
            )
            .scalars()
            .all()
        )
        if not tokens:
            return

        if self.settings.notifications_dry_run:
            logger.info(
                "[DRY RUN] PUSH → user %s (%s tokens): %s — %s",
                user.id,
                len(tokens),
                title,
                body[:120],
            )
            return

        ok = self._push.send_to_tokens(list(tokens), title, body, payload)
        if not ok:
            logger.warning("Push fallido para usuario %s", user.id)

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
