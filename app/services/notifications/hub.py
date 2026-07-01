"""Pub/sub en memoria para notificaciones in-app en tiempo real (SSE)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from app.schemas.notification import NotificationResponse


class NotificationHub:
    def __init__(self) -> None:
        self._queues: dict[int, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, user_id: int) -> asyncio.Queue[dict[str, Any]]:
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=50)
        self._queues[user_id].add(queue)
        return queue

    def unsubscribe(self, user_id: int, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._queues[user_id].discard(queue)
        if not self._queues[user_id]:
            del self._queues[user_id]

    @staticmethod
    def publish_in_app(notifications: list) -> None:
        from app.models.notification import Notification

        for notification in notifications:
            if not isinstance(notification, Notification):
                continue
            if notification.channel != "IN_APP" or notification.user_id is None or notification.id is None:
                continue
            payload = {
                "type": "notification",
                "notification": NotificationResponse.model_validate(notification).model_dump(mode="json"),
            }
            notification_hub.publish(notification.user_id, payload)

    def publish(self, user_id: int, message: dict[str, Any]) -> None:
        queues = list(self._queues.get(user_id, ()))
        if not queues:
            return

        loop = self._loop
        if loop is None:
            return

        def _enqueue() -> None:
            for queue in queues:
                if queue not in self._queues.get(user_id, ()):
                    continue
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    pass

        loop.call_soon_threadsafe(_enqueue)


notification_hub = NotificationHub()
