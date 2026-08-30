from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import ValidationError

from app.models.user import User
from app.core.config import get_settings
from app.schemas.calendly import (
    CalendlyEventCancelRequest,
    CalendlyEventCreateRequest,
    CalendlyEventUpdateRequest,
    CalendlyQuestionAnswerRequest,
)
from app.schemas.chatbot import ChatCalendlyOptions, PendingChatAction
from app.services.calendly.service import CalendlyService
from app.services.chatbot.action_result import ActionResult
from app.services.chatbot.calendly_intents import (
    CANCEL_EVENT_PATTERN,
    CONFIRM_PATTERN,
    CREATE_EVENT_PATTERN,
    EDIT_EVENT_PATTERN,
    LIST_EVENTS_PATTERN,
)
from app.services.chatbot.calendly_options import (
    DEFAULT_TZ,
    day_bounds,
    extract_email,
    format_event_types,
    format_events,
    format_events_reply,
    format_slots,
    parse_date_input,
    resolve_event_id,
    resolve_event_type,
    resolve_slot,
)
from app.services.chatbot.messages import t
from app.services.role_access import can_sell, can_supervise_sales_reps


class CalendlyChatActions:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.db = handler.db
        self.user: User = handler.user
        self.locale = handler.locale
        self.calendly = CalendlyService(handler.db)

    def _can_view(self) -> bool:
        return can_sell(self.user) or can_supervise_sales_reps(self.user)

    def _can_manage(self) -> bool:
        return can_sell(self.user)

    def _can_write(self) -> bool:
        return self._can_manage() and get_settings().calendly_write_enabled

    def _write_disabled_reply(self) -> str:
        return t(
            self.locale,
            "Por ahora solo puedes **consultar** reuniones de Calendly desde el CRM. "
            "Para crear, reprogramar o cancelar, usá Calendly directamente.",
            "For now you can only **view** Calendly meetings from the CRM. "
            "To create, reschedule or cancel, use Calendly directly.",
        )

    def _is_connected(self) -> bool:
        return self.calendly._get_connection_for_user(self.user.id) is not None

    def _not_connected_reply(self) -> str:
        return t(
            self.locale,
            "No tienes Calendly conectado. Conéctalo desde el calendario antes de gestionar reuniones.",
            "Calendly is not connected. Connect it from the calendar page before managing meetings.",
        )

    def _options(
        self,
        *,
        step: str,
        event_types: list[dict[str, Any]] | None = None,
        slots: list[dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
        custom_questions: list[dict[str, Any]] | None = None,
        draft_summary: dict[str, Any] | None = None,
        ready_to_confirm: bool = False,
    ) -> ChatCalendlyOptions:
        return ChatCalendlyOptions(
            step=step,  # type: ignore[arg-type]
            event_types=event_types or [],
            slots=slots or [],
            events=events or [],
            custom_questions=custom_questions or [],
            draft_summary=draft_summary or {},
            ready_to_confirm=ready_to_confirm,
        )

    def _load_event_types(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self.calendly.list_event_types(self.user, user_id=self.user.id)]

    def _active_events(self) -> list[Any]:
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=30)
        return [
            event
            for event in self.calendly.list_events(self.user, user_id=self.user.id, start=now, end=end)
            if event.status == "active"
        ]

    async def handle_selection(self, selection: dict[str, Any]) -> ActionResult | None:
        if not self._can_view():
            return None
        if not self._is_connected():
            return ActionResult(handled=True, reply=self._not_connected_reply())

        kind = selection.get("type")
        if kind in {
            "event_type",
            "date",
            "slot",
            "submit_create",
            "submit_update",
            "cancel_event",
            "start_edit",
            "start_create",
        } and not self._can_write():
            return ActionResult(handled=True, reply=self._write_disabled_reply())
        if kind == "event_type":
            return await self._select_event_type(str(selection.get("uri") or ""), str(selection.get("name") or ""))
        if kind == "date":
            draft = dict(selection.get("draft") or {})
            draft.setdefault("mode", "create")
            draft.setdefault("action", "create_calendly_event")
            return await self._select_date(str(selection.get("value") or ""), draft)
        if kind == "slot":
            draft = dict(selection.get("draft") or {})
            draft.setdefault("action", "create_calendly_event")
            return await self._select_slot(str(selection.get("value") or ""), str(selection.get("label") or ""), draft)
        if kind == "submit_create":
            return await self._submit_create(selection)
        if kind == "submit_update":
            return await self._submit_update(selection)
        if kind == "cancel_event":
            return await self._cancel_event(int(selection.get("event_id")))
        if kind == "start_edit":
            return await self._start_edit_event(int(selection.get("event_id")))
        if kind == "start_create":
            return await self._start_create()
        return None

    async def detect(self, message: str) -> ActionResult | None:
        if not self._can_view():
            return None
        if not self._is_connected():
            if any(
                pattern.search(message)
                for pattern in (LIST_EVENTS_PATTERN, CREATE_EVENT_PATTERN, CANCEL_EVENT_PATTERN, EDIT_EVENT_PATTERN)
            ):
                return ActionResult(handled=True, reply=self._not_connected_reply())
            return None

        if LIST_EVENTS_PATTERN.search(message):
            return await self._list_events(message)
        if CREATE_EVENT_PATTERN.search(message) or CANCEL_EVENT_PATTERN.search(message) or EDIT_EVENT_PATTERN.search(
            message
        ):
            if not self._can_write():
                return ActionResult(handled=True, reply=self._write_disabled_reply())
        if self._can_write() and CREATE_EVENT_PATTERN.search(message):
            return await self._start_create()
        if self._can_write() and CANCEL_EVENT_PATTERN.search(message):
            return await self._start_cancel(message)
        if self._can_write() and EDIT_EVENT_PATTERN.search(message):
            return await self._start_edit(message)
        return None

    async def continue_pending(self, pending: PendingChatAction, message: str) -> ActionResult | None:
        if pending.action in {
            "create_calendly_event",
            "update_calendly_event",
            "cancel_calendly_event",
        } and not self._can_write():
            return ActionResult(handled=True, reply=self._write_disabled_reply())
        if pending.action == "create_calendly_event":
            return await self._continue_create(pending, message)
        if pending.action == "update_calendly_event":
            return await self._continue_update(pending, message)
        if pending.action == "cancel_calendly_event":
            return await self._continue_cancel(pending, message)
        return None

    async def pending_fallback(self, pending: PendingChatAction) -> ActionResult | None:
        if pending.action != "create_calendly_event":
            return None
        types = self._load_event_types()
        return ActionResult(
            handled=True,
            reply=t(
                self.locale,
                "Elegí el **tipo de reunión** (número o nombre).",
                "Choose the **meeting type** (number or name).",
            ),
            pending_action=pending,
            calendly_options=self._options(step="event_type", event_types=format_event_types(types, locale=self.locale)),
        )

    async def _list_events(self, message: str) -> ActionResult:
        lowered = message.lower()
        now = datetime.now(DEFAULT_TZ)
        if "semana" in lowered or "week" in lowered:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
            title = "Reuniones de la semana:" if self.locale != "en" else "Meetings this week:"
        else:
            start, end = day_bounds(now.date().isoformat())
            title = "Reuniones de hoy:" if self.locale != "en" else "Today's meetings:"

        events = self.calendly.list_events(self.user, user_id=self.user.id, start=start, end=end)
        formatted = format_events([event for event in events if event.status == "active"], locale=self.locale)
        if not formatted:
            return ActionResult(
                handled=True,
                reply=format_events_reply(formatted, locale=self.locale, title=title),
                calendly_options=self._options(step="events_list", events=formatted),
            )
        panel_hint = (
            "Usá la lista de abajo para ver tus reuniones."
            if self.locale != "en"
            else "Use the list below to view your meetings."
        )
        if self._can_write():
            panel_hint = (
                "Usá la lista de abajo para reprogramar o cancelar."
                if self.locale != "en"
                else "Use the list below to reschedule or cancel."
            )
        return ActionResult(
            handled=True,
            reply=f"{title}\n\n{panel_hint}",
            calendly_options=self._options(step="events_list", events=formatted),
        )

    async def _start_create(self) -> ActionResult:
        types = self._load_event_types()
        if not types:
            return ActionResult(
                handled=True,
                reply="No hay tipos de evento activos en tu Calendly." if self.locale != "en" else "No active event types found.",
            )
        pending = PendingChatAction(action="create_calendly_event", draft={"step": "event_type", "mode": "create"})
        return ActionResult(
            handled=True,
            reply="Elegí el **tipo de reunión**." if self.locale != "en" else "Choose the **meeting type**.",
            pending_action=pending,
            calendly_options=self._options(step="event_type", event_types=format_event_types(types, locale=self.locale)),
        )

    async def _select_event_type(self, uri: str, name: str) -> ActionResult:
        pending = PendingChatAction(
            action="create_calendly_event",
            draft={"step": "date", "mode": "create", "event_type_uri": uri, "event_type_name": name},
        )
        detail = self.calendly.get_event_type_detail(self.user, event_type_uri=uri, user_id=self.user.id)
        return ActionResult(
            handled=True,
            reply=(
                f"Tipo **{name}**. Dime la **fecha** (MM/DD/YYYY, hoy o mañana)."
                if self.locale != "en"
                else f"Type **{name}**. Tell me the **date** (MM/DD/YYYY, today or tomorrow)."
            ),
            pending_action=pending,
            calendly_options=self._options(
                step="date",
                custom_questions=[q.model_dump() for q in detail.custom_questions],
                draft_summary={"event_type_name": name, "event_type_uri": uri},
            ),
        )

    async def _select_date(self, date_value: str, draft: dict[str, Any]) -> ActionResult:
        base = {**draft, "step": "slot", "date": date_value}
        uri = str(base.get("event_type_uri") or "")
        action = str(base.get("action") or "create_calendly_event")
        start, end = day_bounds(date_value)
        try:
            slots_raw = self.calendly.list_available_times(self.user, event_type_uri=uri, start=start, end=end)
        except HTTPException as exc:
            return ActionResult(handled=True, reply=str(exc.detail))

        slots = format_slots([slot.model_dump() for slot in slots_raw], locale=self.locale)
        if not slots:
            base["step"] = "date"
            return ActionResult(
                handled=True,
                reply=f"No hay horarios el {date_value}. Probá otra fecha.",
                pending_action=PendingChatAction(action=action, draft=base),
                calendly_options=self._options(step="date", draft_summary=base),
            )

        detail = self.calendly.get_event_type_detail(self.user, event_type_uri=uri, user_id=self.user.id)
        base["slots"] = slots
        base["custom_questions"] = [q.model_dump() for q in detail.custom_questions]
        return ActionResult(
            handled=True,
            reply=f"Fecha **{date_value}**. Elegí un **horario**.",
            pending_action=PendingChatAction(action=action, draft=base),
            calendly_options=self._options(step="slot", slots=slots, draft_summary=base, custom_questions=base["custom_questions"]),
        )

    async def _select_slot(self, start_time: str, label: str, draft: dict[str, Any]) -> ActionResult:
        base = {**draft, "step": "invitee", "start_time": start_time, "slot_label": label}
        action = str(base.get("action") or "create_calendly_event")
        return ActionResult(
            handled=True,
            reply="Completa los datos del invitado en el panel o dime nombre y email.",
            pending_action=PendingChatAction(action=action, draft=base),
            calendly_options=self._options(step="invitee", draft_summary=base, custom_questions=base.get("custom_questions") or []),
        )

    async def _continue_create(self, pending: PendingChatAction, message: str) -> ActionResult:
        step = pending.draft.get("step", "event_type")
        if step == "event_type":
            types = self._load_event_types()
            selected = resolve_event_type(message, format_event_types(types, locale=self.locale))
            if not selected:
                return ActionResult(handled=True, reply="No reconocí ese tipo.", pending_action=pending)
            return await self._select_event_type(str(selected["uri"]), str(selected["name"]))
        if step == "date":
            parsed = parse_date_input(message)
            if not parsed:
                return ActionResult(handled=True, reply="Fecha inválida.", pending_action=pending)
            return await self._select_date(parsed, pending.draft)
        if step == "slot":
            selected = resolve_slot(message, pending.draft.get("slots") or [])
            if not selected:
                return ActionResult(handled=True, reply="Horario inválido.", pending_action=pending)
            return await self._select_slot(str(selected["start_time"]), str(selected["label"]), pending.draft)
        if step == "invitee":
            if CONFIRM_PATTERN.match(message.strip()) and pending.draft.get("ready_to_confirm"):
                return await self._confirm_create(pending)
            if not pending.draft.get("invitee_name"):
                pending.draft["invitee_name"] = message.strip()
                return ActionResult(handled=True, reply="Ahora el **email del invitado**.", pending_action=pending)
            if not pending.draft.get("invitee_email"):
                email = extract_email(message)
                if not email:
                    return ActionResult(handled=True, reply="Email inválido.", pending_action=pending)
                pending.draft["invitee_email"] = email
                pending.draft["ready_to_confirm"] = True
                return ActionResult(
                    handled=True,
                    reply=self._create_summary(pending.draft) + "\n\nEscribí **confirmar** o usá el panel.",
                    pending_action=pending,
                    calendly_options=self._options(
                        step="invitee",
                        draft_summary=pending.draft,
                        custom_questions=pending.draft.get("custom_questions") or [],
                        ready_to_confirm=True,
                    ),
                )
        return ActionResult(handled=False, reply="")

    def _create_summary(self, draft: dict[str, Any]) -> str:
        return (
            f"**Resumen**\n- Tipo: {draft.get('event_type_name')}\n"
            f"- Fecha: {draft.get('date')}\n- Horario: {draft.get('slot_label')}\n"
            f"- Invitado: {draft.get('invitee_name')} ({draft.get('invitee_email')})"
        )

    async def _submit_create(self, selection: dict[str, Any]) -> ActionResult:
        pending = PendingChatAction(action="create_calendly_event", draft={**selection, "ready_to_confirm": True})
        return await self._confirm_create(pending)

    async def _confirm_create(self, pending: PendingChatAction) -> ActionResult:
        draft = pending.draft
        try:
            payload = CalendlyEventCreateRequest(
                event_type_uri=str(draft.get("event_type_uri")),
                start_time=datetime.fromisoformat(str(draft.get("start_time")).replace("Z", "+00:00")),
                invitee_name=str(draft.get("invitee_name")),
                invitee_email=str(draft.get("invitee_email")),
                questions_and_answers=[
                    CalendlyQuestionAnswerRequest(question_uuid=str(item["question_uuid"]), answer=str(item.get("answer") or ""))
                    for item in draft.get("questions_and_answers") or []
                    if item.get("question_uuid")
                ],
                timezone=str(DEFAULT_TZ),
            )
            event = self.calendly.create_event(self.user, payload)
        except (HTTPException, ValidationError) as exc:
            detail = getattr(exc, "detail", None) or str(exc)
            return ActionResult(handled=True, reply=f"No pude crear la reunión: {detail}", pending_action=pending)

        return ActionResult(
            handled=True,
            reply=f"✅ Reunión creada: **{event.name}**.",
            calendly_updated=True,
        )

    async def _start_cancel(self, message: str) -> ActionResult:
        events = self._active_events()
        event_id = resolve_event_id(message, format_events(events, locale=self.locale))
        if event_id:
            return await self._cancel_event(event_id)
        return ActionResult(
            handled=True,
            reply="Dime el ID de la reunión a cancelar.",
            pending_action=PendingChatAction(action="cancel_calendly_event", draft={"step": "pick_event"}),
            calendly_options=self._options(step="events_list", events=format_events(events, locale=self.locale)),
        )

    async def _continue_cancel(self, pending: PendingChatAction, message: str) -> ActionResult:
        events = self._active_events()
        event_id = resolve_event_id(message, format_events(events, locale=self.locale))
        if not event_id:
            return ActionResult(handled=True, reply="Reunión no encontrada.", pending_action=pending)
        return await self._cancel_event(event_id)

    async def _cancel_event(self, event_id: int) -> ActionResult:
        try:
            self.calendly.cancel_event(self.user, event_id, CalendlyEventCancelRequest())
        except HTTPException as exc:
            return ActionResult(handled=True, reply=str(exc.detail))
        return ActionResult(handled=True, reply=f"✅ Reunión #{event_id} cancelada.", calendly_updated=True)

    async def _start_edit(self, message: str) -> ActionResult:
        events = self._active_events()
        event_id = resolve_event_id(message, format_events(events, locale=self.locale))
        if event_id:
            return await self._start_edit_event(event_id)
        return ActionResult(
            handled=True,
            reply="Dime qué reunión reprogramar.",
            pending_action=PendingChatAction(action="update_calendly_event", draft={"step": "pick_event"}),
            calendly_options=self._options(step="events_list", events=format_events(events, locale=self.locale)),
        )

    async def _start_edit_event(self, event_id: int) -> ActionResult:
        row = self.calendly._get_owned_event(self.user, event_id)
        types = self._load_event_types()
        pending = PendingChatAction(
            action="update_calendly_event",
            draft={
                "step": "date",
                "mode": "update",
                "event_id": event_id,
                "action": "update_calendly_event",
                "event_type_uri": row.event_type_uri,
                "event_type_name": row.event_type_name,
                "invitee_name": row.invitee_name,
                "invitee_email": row.invitee_email,
            },
        )
        return ActionResult(
            handled=True,
            reply=f"Reprogramando reunión #{event_id}. Dime la **nueva fecha**.",
            pending_action=pending,
            calendly_options=self._options(step="date", draft_summary=pending.draft, event_types=format_event_types(types, locale=self.locale)),
        )

    async def _continue_update(self, pending: PendingChatAction, message: str) -> ActionResult:
        step = pending.draft.get("step", "pick_event")
        if step == "pick_event":
            events = self._active_events()
            event_id = resolve_event_id(message, format_events(events, locale=self.locale))
            if not event_id:
                return ActionResult(handled=True, reply="Reunión no encontrada.", pending_action=pending)
            return await self._start_edit_event(event_id)
        if step == "date":
            parsed = parse_date_input(message)
            if not parsed:
                return ActionResult(handled=True, reply="Fecha inválida.", pending_action=pending)
            return await self._select_date(parsed, pending.draft)
        if step == "slot":
            selected = resolve_slot(message, pending.draft.get("slots") or [])
            if not selected:
                return ActionResult(handled=True, reply="Horario inválido.", pending_action=pending)
            return await self._select_slot(str(selected["start_time"]), str(selected["label"]), pending.draft)
        if step == "invitee" and CONFIRM_PATTERN.match(message.strip()):
            return await self._confirm_update(pending)
        return ActionResult(handled=False, reply="")

    async def _submit_update(self, selection: dict[str, Any]) -> ActionResult:
        pending = PendingChatAction(action="update_calendly_event", draft=dict(selection))
        return await self._confirm_update(pending)

    async def _confirm_update(self, pending: PendingChatAction) -> ActionResult:
        draft = pending.draft
        try:
            payload = CalendlyEventUpdateRequest(
                event_type_uri=str(draft.get("event_type_uri")),
                start_time=datetime.fromisoformat(str(draft.get("start_time")).replace("Z", "+00:00")),
                invitee_name=str(draft.get("invitee_name")),
                invitee_email=str(draft.get("invitee_email")),
                questions_and_answers=[
                    CalendlyQuestionAnswerRequest(question_uuid=str(item["question_uuid"]), answer=str(item.get("answer") or ""))
                    for item in draft.get("questions_and_answers") or []
                    if item.get("question_uuid")
                ],
                timezone=str(DEFAULT_TZ),
            )
            event = self.calendly.update_event(self.user, int(draft.get("event_id")), payload)
        except (HTTPException, ValidationError) as exc:
            detail = getattr(exc, "detail", None) or str(exc)
            return ActionResult(handled=True, reply=f"No pude reprogramar: {detail}", pending_action=pending)
        return ActionResult(handled=True, reply=f"✅ Reunión actualizada: **{event.name}**.", calendly_updated=True)
