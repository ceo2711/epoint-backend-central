"""Sincronización y acceso a Calendly por vendedor."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.encryption import decrypt_value, encrypt_value
from app.models.calendly_connection import CalendlyConnection
from app.models.calendly_event import CalendlyEvent
from app.models.enums import NotificationEventType
from app.models.role import Role
from app.models.user import User
from app.schemas.calendly import (
    CalendlyAvailableTimeResponse,
    CalendlyConnectionResponse,
    CalendlyConnectRequest,
    CalendlyCustomQuestionResponse,
    CalendlyEventCancelRequest,
    CalendlyEventCreateRequest,
    CalendlyEventResponse,
    CalendlyEventTypeResponse,
    CalendlyEventUpdateRequest,
    CalendlyLinkedProspectBrief,
    CalendlyQuestionAnswerRequest,
    CalendlySalesRepItem,
    CalendlySyncResponse,
)
from app.schemas.common import MessageResponse
from app.services.calendly.client import CalendlyApiError, CalendlyClient
from app.services.notifications import NotificationService
from app.services.user_serialization import avatar_url_for

CALENDLY_ROLES = frozenset({"ADMIN", "SALES_REP"})
SYNC_PAST_DAYS = 30
SYNC_FUTURE_DAYS = 180
AUTO_SYNC_STALE_MINUTES = 3


class CalendlyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _event_response(row: CalendlyEvent) -> CalendlyEventResponse:
        linked = None
        prospect = getattr(row, "prospect", None)
        if prospect is not None:
            linked = CalendlyLinkedProspectBrief(
                id=prospect.id,
                full_name=prospect.full_name,
                email=prospect.email,
                converted_client_id=prospect.converted_client_id,
            )
        base = CalendlyEventResponse.model_validate(row)
        return base.model_copy(update={"linked_prospect": linked})

    @staticmethod
    def ensure_calendar_access(actor: User) -> None:
        if actor.role.code not in CALENDLY_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tiene acceso al calendario")

    def _ensure_manage_access(self, actor: User) -> None:
        self.ensure_calendar_access(actor)
        if actor.role.code != "SALES_REP":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo vendedores pueden crear, editar o cancelar reuniones",
            )

    def _client_for_actor(self, actor: User) -> tuple[CalendlyClient, CalendlyConnection]:
        self._ensure_manage_access(actor)
        connection = self._get_connection_for_user(actor.id)
        if connection is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No hay Calendly conectado")
        token = decrypt_value(connection.access_token_encrypted)
        return CalendlyClient(token), connection

    def _get_owned_event(self, actor: User, event_id: int) -> CalendlyEvent:
        self._ensure_manage_access(actor)
        row = self.db.execute(
            select(CalendlyEvent).where(CalendlyEvent.id == event_id, CalendlyEvent.user_id == actor.id)
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evento no encontrado")
        return row

    @staticmethod
    def _format_start_time(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")

    @staticmethod
    def _normalize_comment(value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @staticmethod
    def _event_type_description(resource: dict) -> str | None:
        for key in ("description_plain", "description"):
            value = resource.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _extract_custom_questions(resource: dict) -> list[dict]:
        raw = resource.get("custom_questions")
        return raw if isinstance(raw, list) else []

    @staticmethod
    def _question_id(question: dict, fallback_index: int) -> str:
        uuid = question.get("uuid")
        if uuid:
            return str(uuid)
        uri = question.get("uri")
        if isinstance(uri, str) and uri:
            return uri.rstrip("/").split("/")[-1]
        position = question.get("position")
        if position is not None:
            return f"pos-{position}"
        return f"idx-{fallback_index}"

    @staticmethod
    def _map_custom_questions(raw: list[dict]) -> list[CalendlyCustomQuestionResponse]:
        enabled = [question for question in raw if question.get("enabled", True) and question.get("name")]
        enabled.sort(key=lambda question: int(question.get("position") or 0))
        return [
            CalendlyCustomQuestionResponse(
                uuid=CalendlyService._question_id(question, index),
                name=question.get("name") or "Pregunta",
                type=question.get("type") or "string",
                position=int(question.get("position") or 0),
                required=bool(question.get("required")),
                enabled=bool(question.get("enabled", True)),
                answer_choices=question.get("answer_choices"),
                include_other=question.get("include_other"),
            )
            for index, question in enumerate(enabled)
        ]

    @staticmethod
    def _build_question_answer_payload(question: dict, answer: str) -> dict[str, str | int]:
        payload: dict[str, str | int] = {"answer": answer}
        if question.get("uuid"):
            payload["question_uuid"] = str(question["uuid"])
        else:
            payload["question"] = str(question.get("name") or "")
            payload["position"] = int(question.get("position") or 0)
        return payload

    def _event_type_response_from_resource(self, item: dict, resource: dict) -> CalendlyEventTypeResponse:
        custom_questions = self._extract_custom_questions(resource)
        return CalendlyEventTypeResponse(
            uri=item["uri"],
            name=resource.get("name") or item.get("name") or "Evento",
            duration=int(resource.get("duration") or item.get("duration") or 30),
            scheduling_url=resource.get("scheduling_url") or item.get("scheduling_url"),
            description=self._event_type_description(resource) or self._event_type_description(item),
            custom_questions=self._map_custom_questions(custom_questions),
        )

    @staticmethod
    def _extract_invitee_comment(invitee: dict) -> str | None:
        answers = invitee.get("questions_and_answers") or []
        parts: list[str] = []
        for item in answers:
            question = (item.get("question") or "").strip()
            answer = (item.get("answer") or "").strip()
            if not answer:
                continue
            if question:
                parts.append(f"{question}: {answer}")
            else:
                parts.append(answer)
        if not parts:
            return None
        return "\n".join(parts)

    def _prepare_questions_and_answers(
        self,
        client: CalendlyClient,
        *,
        event_type_uri: str,
        answers: list[CalendlyQuestionAnswerRequest],
        legacy_comment: str | None = None,
    ) -> tuple[list[dict[str, str | int]], str | None]:
        try:
            event_type = client.get_event_type(event_type_uri)
        except CalendlyApiError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        custom_questions = [
            question
            for question in self._extract_custom_questions(event_type)
            if question.get("enabled", True) and question.get("name")
        ]
        custom_questions.sort(key=lambda question: int(question.get("position") or 0))
        answers_by_uuid = {item.question_uuid: (item.answer or "").strip() for item in answers}

        normalized_legacy = self._normalize_comment(legacy_comment)
        if normalized_legacy and not any(answers_by_uuid.values()) and len(custom_questions) == 1:
            answers_by_uuid[self._question_id(custom_questions[0], 0)] = normalized_legacy

        payload: list[dict[str, str | int]] = []
        stored_parts: list[str] = []
        for index, question in enumerate(custom_questions):
            question_key = self._question_id(question, index)
            answer = answers_by_uuid.get(question_key, "").strip()
            if not answer and question.get("uuid"):
                answer = answers_by_uuid.get(str(question["uuid"]), "").strip()
            question_name = question.get("name") or "Pregunta"
            if question.get("required") and not answer:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Completá el campo obligatorio: {question_name}",
                )
            if answer:
                payload.append(self._build_question_answer_payload(question, answer))
                stored_parts.append(f"{question_name}: {answer}")

        stored_comment = "\n".join(stored_parts) if stored_parts else normalized_legacy
        return payload, stored_comment

    def _book_invitee(
        self,
        client: CalendlyClient,
        *,
        event_type_uri: str,
        start_time: datetime,
        invitee_name: str,
        invitee_email: str,
        timezone_name: str | None,
        questions_and_answers: list[dict[str, str | int]] | None = None,
    ) -> None:
        try:
            client.create_invitee(
                event_type_uri=event_type_uri,
                start_time=self._format_start_time(start_time),
                name=invitee_name,
                email=invitee_email,
                timezone=timezone_name,
                questions_and_answers=questions_and_answers,
            )
        except CalendlyApiError as exc:
            if exc.status_code == 400:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El horario seleccionado no está disponible en Calendly. Elegí otro slot.",
                ) from exc
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    def list_event_types(self, actor: User, *, user_id: int | None = None) -> list[CalendlyEventTypeResponse]:
        target_user_id = self._resolve_target_user_id(actor, user_id)
        connection = self._get_connection_for_user(target_user_id)
        if connection is None:
            return []

        token = decrypt_value(connection.access_token_encrypted)
        client = CalendlyClient(token)
        try:
            items = client.list_event_types(user_uri=connection.calendly_user_uri)
        except CalendlyApiError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        results: list[CalendlyEventTypeResponse] = []
        for item in items:
            if not item.get("uri") or item.get("kind") == "AdhocEventType":
                continue

            try:
                resource = client.get_event_type(item["uri"])
            except CalendlyApiError:
                resource = item

            results.append(self._event_type_response_from_resource(item, resource))
        return results

    def get_event_type_detail(
        self,
        actor: User,
        *,
        event_type_uri: str,
        user_id: int | None = None,
    ) -> CalendlyEventTypeResponse:
        target_user_id = self._resolve_target_user_id(actor, user_id)
        connection = self._get_connection_for_user(target_user_id)
        if connection is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No hay Calendly conectado")

        token = decrypt_value(connection.access_token_encrypted)
        client = CalendlyClient(token)
        try:
            resource = client.get_event_type(event_type_uri)
        except CalendlyApiError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        if not resource.get("uri"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tipo de evento no encontrado")

        return self._event_type_response_from_resource({"uri": resource["uri"]}, resource)

    def list_available_times(
        self,
        actor: User,
        *,
        event_type_uri: str,
        start: datetime,
        end: datetime,
    ) -> list[CalendlyAvailableTimeResponse]:
        client, _connection = self._client_for_actor(actor)
        now = datetime.now(timezone.utc)
        effective_start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        effective_end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        if effective_start < now:
            effective_start = now
        if effective_start >= effective_end:
            return []

        try:
            slots = client.list_available_times(
                event_type_uri=event_type_uri,
                start_time=self._format_start_time(effective_start),
                end_time=self._format_start_time(effective_end),
            )
        except CalendlyApiError as exc:
            if exc.status_code == 400 and "future" in str(exc).lower():
                return []
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        results: list[CalendlyAvailableTimeResponse] = []
        for slot in slots:
            start_raw = slot.get("start_time")
            if not start_raw:
                continue
            results.append(
                CalendlyAvailableTimeResponse(
                    start_time=datetime.fromisoformat(start_raw.replace("Z", "+00:00")),
                    status=slot.get("status") or "available",
                )
            )
        return results

    def create_event(self, actor: User, payload: CalendlyEventCreateRequest) -> CalendlyEventResponse:
        client, _connection = self._client_for_actor(actor)
        questions_payload, stored_comment = self._prepare_questions_and_answers(
            client,
            event_type_uri=payload.event_type_uri,
            answers=payload.questions_and_answers,
            legacy_comment=payload.invitee_comment,
        )
        self._book_invitee(
            client,
            event_type_uri=payload.event_type_uri,
            start_time=payload.start_time,
            invitee_name=payload.invitee_name.strip(),
            invitee_email=str(payload.invitee_email),
            timezone_name=payload.timezone,
            questions_and_answers=questions_payload or None,
        )
        self.sync_events(actor, user_id=actor.id, notify_new_events=False)
        response = self._find_event_after_booking(actor, payload.invitee_email, payload.start_time)
        if stored_comment:
            row = self.db.get(CalendlyEvent, response.id)
            if row is not None:
                row.invitee_comment = stored_comment
                self.db.commit()
                return self._event_response(row)
        return response

    def _find_event_after_booking(
        self,
        actor: User,
        invitee_email: str,
        start_time: datetime,
    ) -> CalendlyEventResponse:
        target_start = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)
        rows = self.db.execute(
            select(CalendlyEvent).where(
                CalendlyEvent.user_id == actor.id,
                CalendlyEvent.status == "active",
                CalendlyEvent.invitee_email == str(invitee_email),
            )
        ).scalars().all()
        for row in rows:
            row_start = row.start_time if row.start_time.tzinfo else row.start_time.replace(tzinfo=timezone.utc)
            if abs((row_start - target_start).total_seconds()) < 90:
                return self._event_response(row)
        if rows:
            return self._event_response(max(rows, key=lambda item: item.start_time))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Evento creado en Calendly pero no se pudo sincronizar",
        )

    def update_event(
        self,
        actor: User,
        event_id: int,
        payload: CalendlyEventUpdateRequest,
    ) -> CalendlyEventResponse:
        client, _connection = self._client_for_actor(actor)
        row = self._get_owned_event(actor, event_id)
        if row.status == "canceled":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No se puede editar un evento cancelado")

        old_start = row.start_time
        old_email = row.invitee_email
        invitee_comment = self._normalize_comment(row.invitee_comment)
        questions_payload, stored_comment = self._prepare_questions_and_answers(
            client,
            event_type_uri=payload.event_type_uri,
            answers=payload.questions_and_answers,
            legacy_comment=payload.invitee_comment,
        )
        same_slot = (
            payload.event_type_uri == row.event_type_uri
            and payload.start_time.replace(tzinfo=timezone.utc)
            == (old_start if old_start.tzinfo else old_start.replace(tzinfo=timezone.utc))
            and str(payload.invitee_email) == old_email
            and payload.invitee_name.strip() == row.invitee_name
            and stored_comment == invitee_comment
        )
        if same_slot:
            return self._event_response(row)

        try:
            client.cancel_scheduled_event(
                row.calendly_event_uri,
                reason="Reprogramado desde ePoint Central",
            )
        except CalendlyApiError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        row.status = "canceled"
        self.db.commit()

        self._book_invitee(
            client,
            event_type_uri=payload.event_type_uri,
            start_time=payload.start_time,
            invitee_name=payload.invitee_name.strip(),
            invitee_email=str(payload.invitee_email),
            timezone_name=payload.timezone,
            questions_and_answers=questions_payload or None,
        )
        self.sync_events(actor, user_id=actor.id, notify_new_events=False)
        response = self._find_event_after_booking(actor, payload.invitee_email, payload.start_time)
        if stored_comment:
            new_row = self.db.get(CalendlyEvent, response.id)
            if new_row is not None:
                new_row.invitee_comment = stored_comment
                self.db.commit()
                return self._event_response(new_row)
        return response

    def cancel_event(self, actor: User, event_id: int, payload: CalendlyEventCancelRequest) -> MessageResponse:
        client, _connection = self._client_for_actor(actor)
        row = self._get_owned_event(actor, event_id)
        if row.status == "canceled":
            return MessageResponse(message="El evento ya estaba cancelado")

        try:
            client.cancel_scheduled_event(row.calendly_event_uri, reason=payload.reason)
        except CalendlyApiError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        row.status = "canceled"
        self.db.commit()
        return MessageResponse(message="Reunión cancelada en Calendly")

    def _resolve_target_user_id(self, actor: User, user_id: int | None) -> int:
        self.ensure_calendar_access(actor)
        if actor.role.code == "SALES_REP":
            if user_id is not None and user_id != actor.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No puede ver el calendario de otro usuario",
                )
            return actor.id
        if actor.role.code == "ADMIN":
            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="user_id es requerido para ver el calendario de un vendedor",
                )
            return user_id
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puede ver el calendario de otro usuario")

    def _get_connection_for_user(self, user_id: int) -> CalendlyConnection | None:
        return self.db.execute(
            select(CalendlyConnection).where(CalendlyConnection.user_id == user_id)
        ).scalar_one_or_none()

    def _connection_response(self, connection: CalendlyConnection | None, *, user_id: int) -> CalendlyConnectionResponse:
        if connection is None:
            return CalendlyConnectionResponse(connected=False, user_id=user_id)
        return CalendlyConnectionResponse(
            connected=True,
            user_id=user_id,
            calendly_user_name=connection.calendly_user_name,
            scheduling_url=connection.scheduling_url,
            last_synced_at=connection.last_synced_at,
        )

    def get_connection(self, actor: User, *, user_id: int | None = None) -> CalendlyConnectionResponse:
        target_user_id = self._resolve_target_user_id(actor, user_id)
        connection = self._get_connection_for_user(target_user_id)
        return self._connection_response(connection, user_id=target_user_id)

    def list_sales_reps(self, actor: User) -> list[CalendlySalesRepItem]:
        self.ensure_calendar_access(actor)
        if actor.role.code != "ADMIN":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo administradores")

        users = (
            self.db.execute(
                select(User)
                .join(Role)
                .options(joinedload(User.calendly_connection))
                .where(Role.code == "SALES_REP", User.is_active.is_(True))
                .order_by(User.first_name, User.last_name)
            )
            .unique()
            .scalars()
            .all()
        )

        items: list[CalendlySalesRepItem] = []
        for user in users:
            connection = user.calendly_connection
            items.append(
                CalendlySalesRepItem(
                    id=user.id,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    email=user.email,
                    connected=connection is not None,
                    scheduling_url=connection.scheduling_url if connection else None,
                    last_synced_at=connection.last_synced_at if connection else None,
                    avatar_url=avatar_url_for(user),
                )
            )
        return items

    def connect(self, actor: User, payload: CalendlyConnectRequest) -> CalendlyConnectionResponse:
        self.ensure_calendar_access(actor)
        if actor.role.code != "SALES_REP" and actor.role.code != "ADMIN":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo vendedores pueden conectar Calendly")
        if actor.role.code == "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Los administradores deben ver el calendario de cada vendedor; la conexión es por vendedor",
            )

        client = CalendlyClient(payload.access_token)
        try:
            calendly_user = client.get_current_user()
        except CalendlyApiError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        user_uri = calendly_user.get("uri")
        if not user_uri:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Respuesta inválida de Calendly")

        scheduling_url = (
            str(payload.scheduling_url)
            if payload.scheduling_url
            else calendly_user.get("scheduling_url") or ""
        )
        if not scheduling_url:
            slug = calendly_user.get("slug")
            if slug:
                scheduling_url = f"https://calendly.com/{slug}"
        if not scheduling_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se pudo determinar la URL pública de agendamiento. Ingresala manualmente.",
            )

        connection = self._get_connection_for_user(actor.id)
        if connection is None:
            connection = CalendlyConnection(user_id=actor.id)
            self.db.add(connection)

        connection.calendly_user_uri = user_uri
        connection.calendly_user_name = calendly_user.get("name") or actor.full_name
        connection.calendly_user_slug = calendly_user.get("slug")
        connection.scheduling_url = scheduling_url.rstrip("/")
        connection.access_token_encrypted = encrypt_value(payload.access_token.strip())
        self.db.commit()
        self.db.refresh(connection)

        sync_result = self.sync_events(actor, user_id=actor.id)
        connection.last_synced_at = sync_result.last_synced_at
        self.db.commit()

        return self._connection_response(connection, user_id=actor.id)

    def disconnect(self, actor: User) -> MessageResponse:
        self.ensure_calendar_access(actor)
        if actor.role.code != "SALES_REP":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo vendedores pueden desconectar Calendly")

        connection = self._get_connection_for_user(actor.id)
        if connection is None:
            return MessageResponse(message="No hay cuenta de Calendly conectada")

        self.db.delete(connection)
        self.db.commit()
        return MessageResponse(message="Cuenta de Calendly desconectada")

    def sync_events(
        self,
        actor: User,
        *,
        user_id: int | None = None,
        notify_new_events: bool = True,
    ) -> CalendlySyncResponse:
        target_user_id = self._resolve_target_user_id(actor, user_id)
        if actor.role.code == "SALES_REP" and target_user_id != actor.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puede sincronizar otro calendario")

        connection = self._get_connection_for_user(target_user_id)
        if connection is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El vendedor no tiene Calendly conectado")

        token = decrypt_value(connection.access_token_encrypted)
        client = CalendlyClient(token)
        now = datetime.now(timezone.utc)
        min_start = (now - timedelta(days=SYNC_PAST_DAYS)).isoformat()
        max_start = (now + timedelta(days=SYNC_FUTURE_DAYS)).isoformat()

        try:
            remote_events = client.list_scheduled_events(
                user_uri=connection.calendly_user_uri,
                min_start_time=min_start,
                max_start_time=max_start,
            )
        except CalendlyApiError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        previous_sync = connection.last_synced_at
        if previous_sync is not None and previous_sync.tzinfo is None:
            previous_sync = previous_sync.replace(tzinfo=timezone.utc)
        is_initial_sync = previous_sync is None

        synced = 0
        new_active_events: list[CalendlyEvent] = []
        for remote in remote_events:
            event_uri = remote.get("uri")
            if not event_uri:
                continue

            invitee_name = None
            invitee_email = None
            invitee_comment = None
            try:
                invitees = client.list_event_invitees(event_uri)
                if invitees:
                    invitee_name = invitees[0].get("name")
                    invitee_email = invitees[0].get("email")
                    invitee_comment = self._extract_invitee_comment(invitees[0])
            except CalendlyApiError:
                pass

            event_type_uri = remote.get("event_type")
            event_type_name = None
            try:
                event_type_name = client.get_event_type_name(event_type_uri)
            except CalendlyApiError:
                event_type_name = remote.get("name")

            location_data = remote.get("location") or {}
            meeting_url = location_data.get("join_url") or location_data.get("location")
            location_label = location_data.get("type")

            row = self.db.execute(
                select(CalendlyEvent).where(CalendlyEvent.calendly_event_uri == event_uri)
            ).scalar_one_or_none()
            is_new = row is None
            if is_new:
                row = CalendlyEvent(user_id=target_user_id, calendly_event_uri=event_uri)
                self.db.add(row)

            row.name = remote.get("name") or "Reunión"
            row.status = remote.get("status") or "active"
            row.start_time = datetime.fromisoformat(remote["start_time"].replace("Z", "+00:00"))
            row.end_time = datetime.fromisoformat(remote["end_time"].replace("Z", "+00:00"))
            row.event_type_name = event_type_name
            row.event_type_uri = event_type_uri
            row.invitee_name = invitee_name
            row.invitee_email = invitee_email
            if invitee_comment is not None:
                row.invitee_comment = invitee_comment
            row.location = location_label
            row.meeting_url = meeting_url
            synced += 1

            if (
                notify_new_events
                and not is_initial_sync
                and is_new
                and row.status == "active"
            ):
                new_active_events.append(row)

        created_notifications: list = []
        if new_active_events:
            self.db.flush()
            sales_rep = self.db.get(User, target_user_id)
            if sales_rep is not None:
                notifications = NotificationService(self.db)
                for event in new_active_events:
                    start_time = event.start_time
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=timezone.utc)
                    start_label = start_time.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
                    invitee = event.invitee_name or event.invitee_email or "Un invitado"
                    meeting_name = event.event_type_name or event.name
                    created_notifications.extend(
                        notifications.notify(
                            event_type=NotificationEventType.CALENDLY_EVENT_SCHEDULED.value,
                            users=[sales_rep],
                            title="Nueva reunión agendada",
                            body=f"{invitee} agendó «{meeting_name}» el {start_label}.",
                            payload={
                                "calendly_event_id": event.id,
                                "start_time": start_time.isoformat(),
                            },
                            commit=False,
                        )
                    )

        connection.last_synced_at = now
        self.db.commit()
        if created_notifications:
            from app.services.notifications.hub import notification_hub

            notification_hub.publish_in_app(created_notifications)
        return CalendlySyncResponse(synced_count=synced, last_synced_at=now)

    def list_events(
        self,
        actor: User,
        *,
        user_id: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[CalendlyEventResponse]:
        target_user_id = self._resolve_target_user_id(actor, user_id)
        connection = self._get_connection_for_user(target_user_id)
        if connection is not None:
            now = datetime.now(timezone.utc)
            last_synced = connection.last_synced_at
            if last_synced is not None and last_synced.tzinfo is None:
                last_synced = last_synced.replace(tzinfo=timezone.utc)
            stale = last_synced is None or (now - last_synced) > timedelta(minutes=AUTO_SYNC_STALE_MINUTES)
            if stale:
                try:
                    self.sync_events(actor, user_id=target_user_id)
                except HTTPException:
                    pass

        query = select(CalendlyEvent).where(CalendlyEvent.user_id == target_user_id)
        if start is not None:
            query = query.where(CalendlyEvent.start_time >= start)
        if end is not None:
            query = query.where(CalendlyEvent.start_time <= end)
        rows = (
            self.db.execute(
                query.options(joinedload(CalendlyEvent.prospect)).order_by(CalendlyEvent.start_time.asc())
            )
            .unique()
            .scalars()
            .all()
        )
        return [self._event_response(row) for row in rows]
