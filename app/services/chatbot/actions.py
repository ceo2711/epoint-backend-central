import json
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_user_permissions
from app.models.client import Client
from app.models.enums import ClientSource, ClientStatus
from app.models.merchant import Merchant
from app.services.merchant_context import MerchantContextService
from app.models.role import Role
from app.models.user import User
from app.schemas.chatbot import PendingChatAction, ClientApprovalResult, ChatUploadOptions
from app.services.chatbot.action_result import ActionResult
from app.services.chatbot.calendly_actions import CalendlyChatActions
from app.services.chatbot.approval_intents import (
    APPROVE_ONE_ID_PATTERN,
    REJECT_ONE_ID_PATTERN,
    looks_like_approve_all,
    looks_like_approve_one,
    looks_like_reject_all,
    looks_like_reject_one,
)
from app.services.chatbot.approval_rules import validate_approval_requirements
from app.services.chatbot.context import CLIENT_ROLE, SALES_ROLE, STAFF_ROLES, ChatbotContextBuilder
from app.services.chatbot.report import format_client_report, format_pending_approval_answer
from app.services.chatbot.registration_options import resolve_merchant_id, resolve_source
from app.services.chatbot.upload_options import (
    UPLOAD_BOARD_INTENT_PATTERN,
    UPLOAD_DOCUMENT_INTENT_PATTERN,
    document_type_label,
    list_board_card_options,
    list_document_type_options,
    resolve_board_card_id,
    resolve_document_type,
)
from app.services.chatbot.messages import (
    friendly_advisor_prompt,
    friendly_approve_one_intro,
    friendly_approve_success,
    friendly_cancel,
    friendly_register_error,
    friendly_register_missing,
    friendly_register_success,
    friendly_bulk_register_result,
    friendly_registration_meta_reply,
    friendly_reject_one_intro,
    friendly_upload_board_need_card,
    friendly_upload_board_need_client,
    friendly_upload_board_ready,
    friendly_upload_board_start,
    friendly_upload_document_need_client,
    friendly_upload_document_need_type,
    friendly_upload_document_ready,
    friendly_upload_document_start,
    friendly_verify_pending_footer,
    t,
)
from app.services.clients import ClientService
from app.services.llm import get_llm_service

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"\+?[\d][\d\s\-()]{7,}[\d]")

CANCEL_PATTERN = re.compile(
    r"^(cancelar|cancel|olvida(?:lo)?|detener|abortar)(?:\s|$)",
    re.IGNORECASE,
)

VERIFY_PENDING_PATTERN = re.compile(
    r"(?:verificar|revisar|validar)(?:\s+los?)?\s+(?:clientes?\s+)?pendientes?",
    re.IGNORECASE,
)
PENDING_APPROVAL_QUERY_PATTERN = re.compile(
    r"(?:tengo|hay|tiene(?:n)?)\s+(?:algun(?:o|a)?\s+)?(?:cliente[s]?\s+)?(?:pendiente[s]?|por\s+aprobar|de\s+(?:revision|revisión|aprobacion|aprobación))"
    r"|(?:cuantos?|cuántos?)\s+(?:clientes?\s+)?(?:pendiente[s]?|por\s+aprobar|de\s+(?:revision|revisión|aprobacion|aprobación))"
    r"|(?:clientes?\s+)?pendiente[s]?\s+(?:de\s+)?(?:revision|revisión|aprobacion|aprobación)",
    re.IGNORECASE,
)
CLIENT_REPORT_PATTERN = re.compile(
    r"(?:informe|reporte|resumen|estado)\s+(?:completo\s+)?(?:del?\s+)?(?:cliente|de\b)"
    r"|(?:dame|mostrar|ver|quiero|necesito)\s+(?:un\s+)?(?:informe|reporte|resumen|estado)\s+(?:completo\s+)?"
    r"|informe\s+completo",
    re.IGNORECASE,
)
from app.services.chatbot.registration_intents import (
    REGISTER_INTENT_PATTERN,
    is_registration_meta_question,
    looks_like_person_name,
)
from app.services.chatbot.registration_bulk import (
    looks_like_structured_registration_block,
    parse_bulk_registration_blocks,
)
NAME_PREFIX_PATTERN = re.compile(
    r"^(?:quiero\s+)?(?:registrar|crear|agregar|dar\s+de\s+alta|cargar|nuevo|alta\s+de)"
    r"(?:\s+(?:un|una|cliente[s]?))?"
    r"(?:(?:\s+a|\s+al)(?=\s)|(?:\s+a|\s+al)$)?\s*",
    re.IGNORECASE,
)
NAME_PATTERN = re.compile(
    r"^[A-Za-zÁÉÍÓÚáéíóúÑñ][A-Za-zÁÉÍÓÚáéíóúÑñ'\-]*(?:\s+[A-Za-zÁÉÍÓÚáéíóúÑñ][A-Za-zÁÉÍÓÚáéíóúÑñ'\-]*)+$",
)

STAFF_UPLOAD_ROLES = STAFF_ROLES | {"ADMIN", "BRANCH_MANAGER"}


class ChatbotActionHandler:
    def __init__(self, db: Session, user: User, *, locale: str = "es", merchant_id: int | None = None) -> None:
        self.db = db
        self.user = user
        self.locale = locale
        self.merchant_id = merchant_id
        self.clients = ClientService(db)
        self.permissions = set(get_user_permissions(db, user))
        if user.role.code in ("ADMIN", "BRANCH_MANAGER"):
            self.permissions |= {"clients:create", "clients:approve", "clients:read"}

    async def handle(
        self,
        *,
        message: str,
        pending_action: PendingChatAction | None,
        locale: str | None = None,
        client_id: int | None = None,
        calendly_selection: dict[str, Any] | None = None,
    ) -> ActionResult | None:
        if locale:
            self.locale = locale

        calendly = CalendlyChatActions(self)
        if calendly_selection:
            result = await calendly.handle_selection(calendly_selection)
            if result:
                return result

        if CANCEL_PATTERN.match(message.strip()):
            if pending_action:
                return ActionResult(
                    handled=True,
                    reply=friendly_cancel(self.locale),
                    pending_action=None,
                )
            return None

        if pending_action:
            calendly_result = await calendly.continue_pending(pending_action, message)
            if calendly_result and calendly_result.handled:
                return calendly_result

            result = await self._continue_pending(pending_action, message, client_id=client_id)
            if result.handled:
                return result
            if pending_action.action == "register_client":
                return ActionResult(
                    handled=True,
                    reply=self._register_reply(pending_action.draft),
                    pending_action=pending_action,
                )
            if pending_action.action == "approve_client":
                client = self.db.get(Client, pending_action.client_id)
                if client is None:
                    return ActionResult(handled=True, reply="El cliente ya no existe.", pending_action=None)
                return self._approve_client(client)
            if pending_action.action == "approve_all":
                clients = [self.db.get(Client, cid) for cid in pending_action.client_ids]
                clients = [c for c in clients if c is not None]
                return self._approve_all(clients)
            if pending_action.action == "reject_client":
                client = self.db.get(Client, pending_action.client_id)
                name = client.full_name if client else "el cliente"
                return ActionResult(
                    handled=True,
                    reply=friendly_reject_one_intro(self.locale, full_name=name),
                    pending_action=pending_action,
                )
            if pending_action.action == "reject_all":
                return ActionResult(
                    handled=True,
                    reply="Escribí el **motivo del rechazo** para aplicarlo a todos los pendientes.",
                    pending_action=pending_action,
                )
            if pending_action.action == "upload_document":
                return ActionResult(
                    handled=True,
                    reply=friendly_upload_document_need_type(self.locale),
                    pending_action=pending_action,
                    client_id=pending_action.client_id or client_id,
                    upload_options=self._document_upload_options(ready=bool(pending_action.draft.get("document_type"))),
                )
            if pending_action.action == "upload_board_attachment":
                resolved = pending_action.client_id or client_id
                return ActionResult(
                    handled=True,
                    reply=friendly_upload_board_need_card(self.locale),
                    pending_action=pending_action,
                    client_id=resolved,
                    upload_options=self._board_upload_options(resolved, ready=bool(pending_action.draft.get("card_id")))
                    if resolved
                    else None,
                )
            calendly_fallback = await calendly.pending_fallback(pending_action)
            if calendly_fallback:
                return calendly_fallback

        calendly_detected = await calendly.detect(message)
        if calendly_detected:
            return calendly_detected

        return await self._detect_and_run(message, client_id=client_id)

    def _looks_like_client_registration(self, message: str) -> bool:
        if looks_like_structured_registration_block(message):
            return True
        has_email = bool(EMAIL_PATTERN.search(message))
        has_phone = bool(PHONE_PATTERN.search(message))
        first, last = self._extract_name_from_message(message)
        has_full_name = looks_like_person_name(first, last)
        return (has_email and has_phone) or (has_full_name and (has_email or has_phone))

    async def _detect_and_run(self, message: str, *, client_id: int | None = None) -> ActionResult | None:
        if self._can_view_client_report() and CLIENT_REPORT_PATTERN.search(message):
            return self._client_report(message, client_id)

        if self._can_upload_documents() and UPLOAD_DOCUMENT_INTENT_PATTERN.search(message):
            return await self._start_upload_document(message, client_id)

        if self._can_upload_board_attachments() and UPLOAD_BOARD_INTENT_PATTERN.search(message):
            return await self._start_upload_board_attachment(message, client_id)

        if self._can_create():
            if is_registration_meta_question(message):
                return ActionResult(
                    handled=True,
                    reply=friendly_registration_meta_reply(self.locale),
                )
            if (
                REGISTER_INTENT_PATTERN.search(message)
                or self._looks_like_client_registration(message)
            ):
                return await self._start_register_client(message)

        if self._can_approve():
            if PENDING_APPROVAL_QUERY_PATTERN.search(message):
                return self._answer_pending_approval_query()

            if VERIFY_PENDING_PATTERN.search(message):
                return self._verify_pending_clients()

            if looks_like_approve_all(message):
                return await self._start_approve_all()

            if looks_like_reject_all(message):
                return self._start_reject_all()

            match = APPROVE_ONE_ID_PATTERN.search(message)
            if match:
                return await self._start_approve_one(int(match.group(1)))

            match = REJECT_ONE_ID_PATTERN.search(message)
            if match:
                return self._start_reject_one(int(match.group(1)))

            if looks_like_approve_one(message):
                client_id = self._resolve_pending_client_id(message)
                if client_id:
                    return await self._start_approve_one(client_id)

            if looks_like_reject_one(message):
                client_id = self._resolve_pending_client_id(message)
                if client_id:
                    return self._start_reject_one(client_id)

        return None

    async def _continue_pending(
        self, pending: PendingChatAction, message: str, *, client_id: int | None = None
    ) -> ActionResult:
        if pending.action == "register_client":
            return await self._continue_register(pending, message)
        if pending.action == "approve_client":
            return await self._continue_approve_one(pending, message)
        if pending.action == "reject_client":
            return self._continue_reject_one(pending, message)
        if pending.action == "approve_all":
            return await self._continue_approve_all(pending, message)
        if pending.action == "reject_all":
            return self._continue_reject_all(pending, message)
        if pending.action == "upload_document":
            return await self._continue_upload_document(pending, message, client_id)
        if pending.action == "upload_board_attachment":
            return await self._continue_upload_board_attachment(pending, message, client_id)
        return ActionResult(handled=False, reply="")

    def _can_create(self) -> bool:
        return "clients:create" in self.permissions

    def _can_approve(self) -> bool:
        return "clients:approve" in self.permissions

    def _can_view_client_report(self) -> bool:
        if self.user.role.code == CLIENT_ROLE:
            return False
        if self.user.role.code in STAFF_ROLES | {SALES_ROLE, "ADMIN", "BRANCH_MANAGER"}:
            return "clients:read" in self.permissions or self.user.role.code in ("ADMIN", "BRANCH_MANAGER")
        return False

    def _can_upload_documents(self) -> bool:
        from app.services.role_access import can_upload_client_documents

        return can_upload_client_documents(self.user)

    def _can_upload_board_attachments(self) -> bool:
        return self.user.role.code in STAFF_UPLOAD_ROLES

    def _resolve_upload_client_id(
        self,
        message: str,
        client_id: int | None,
        pending: PendingChatAction | None,
    ) -> int | None:
        if pending and pending.client_id:
            if self.clients.user_can_access_client(self.user, pending.client_id):
                return pending.client_id
        if client_id and self.clients.user_can_access_client(self.user, client_id):
            return client_id
        if self.user.role.code == CLIENT_ROLE:
            return self.user.client_id
        from app.services.chatbot.context import ChatbotContextBuilder

        return ChatbotContextBuilder(self.db, self.user, merchant_id=self.merchant_id).resolve_client_id(message, None)

    def _document_upload_options(self, *, ready: bool) -> ChatUploadOptions:
        return ChatUploadOptions(
            kind="document",
            document_types=list_document_type_options(self.locale),
            ready_for_file=ready,
        )

    def _board_upload_options(self, client_id: int, *, ready: bool) -> ChatUploadOptions:
        return ChatUploadOptions(
            kind="board_card",
            board_cards=list_board_card_options(self.db, client_id),
            ready_for_file=ready,
        )

    async def _start_upload_document(self, message: str, client_id: int | None) -> ActionResult:
        resolved_client = self._resolve_upload_client_id(message, client_id, None)
        if not resolved_client and self.user.role.code != CLIENT_ROLE:
            return ActionResult(
                handled=True,
                reply=friendly_upload_document_need_client(self.locale),
                pending_action=PendingChatAction(action="upload_document", draft={}),
                upload_options=self._document_upload_options(ready=False),
            )

        draft: dict[str, Any] = {}
        doc_type = resolve_document_type(message)
        if doc_type:
            draft["document_type"] = doc_type

        pending = PendingChatAction(
            action="upload_document",
            client_id=resolved_client,
            draft=draft,
        )

        if doc_type:
            label = document_type_label(doc_type, self.locale)
            return ActionResult(
                handled=True,
                reply=friendly_upload_document_ready(self.locale, document_label=label),
                pending_action=pending,
                client_id=resolved_client,
                upload_options=self._document_upload_options(ready=True),
            )

        return ActionResult(
            handled=True,
            reply=(
                friendly_upload_document_start(self.locale, for_staff=self.user.role.code != CLIENT_ROLE)
                + "\n\n"
                + friendly_upload_document_need_type(self.locale)
            ),
            pending_action=pending,
            client_id=resolved_client,
            upload_options=self._document_upload_options(ready=False),
        )

    async def _continue_upload_document(
        self,
        pending: PendingChatAction,
        message: str,
        client_id: int | None,
    ) -> ActionResult:
        draft = dict(pending.draft)
        resolved_client = self._resolve_upload_client_id(message, client_id, pending)
        if not resolved_client and self.user.role.code != CLIENT_ROLE:
            return ActionResult(
                handled=True,
                reply=friendly_upload_document_need_client(self.locale),
                pending_action=PendingChatAction(action="upload_document", draft=draft),
                upload_options=self._document_upload_options(ready=False),
            )

        doc_type = draft.get("document_type") or resolve_document_type(message)
        if doc_type:
            draft["document_type"] = doc_type

        pending = PendingChatAction(
            action="upload_document",
            client_id=resolved_client,
            draft=draft,
        )

        if not draft.get("document_type"):
            return ActionResult(
                handled=True,
                reply=friendly_upload_document_need_type(self.locale),
                pending_action=pending,
                client_id=resolved_client,
                upload_options=self._document_upload_options(ready=False),
            )

        label = document_type_label(str(draft["document_type"]), self.locale)
        return ActionResult(
            handled=True,
            reply=friendly_upload_document_ready(self.locale, document_label=label),
            pending_action=pending,
            client_id=resolved_client,
            upload_options=self._document_upload_options(ready=True),
        )

    async def _start_upload_board_attachment(self, message: str, client_id: int | None) -> ActionResult:
        resolved_client = self._resolve_upload_client_id(message, client_id, None)
        if not resolved_client:
            return ActionResult(
                handled=True,
                reply=friendly_upload_board_need_client(self.locale),
                pending_action=PendingChatAction(action="upload_board_attachment", draft={}),
            )

        cards = list_board_card_options(self.db, resolved_client)
        if not cards:
            return ActionResult(
                handled=True,
                reply=t(
                    self.locale,
                    "Este cliente aún no tiene tablero de onboarding.",
                    "This client does not have an onboarding board yet.",
                ),
                pending_action=None,
                client_id=resolved_client,
            )

        draft: dict[str, Any] = {}
        card_id = resolve_board_card_id(message, cards)
        if card_id:
            draft["card_id"] = card_id

        pending = PendingChatAction(
            action="upload_board_attachment",
            client_id=resolved_client,
            draft=draft,
        )

        if card_id:
            card_title = next(str(card["title"]) for card in cards if card["id"] == card_id)
            return ActionResult(
                handled=True,
                reply=friendly_upload_board_ready(self.locale, card_title=card_title),
                pending_action=pending,
                client_id=resolved_client,
                upload_options=self._board_upload_options(resolved_client, ready=True),
            )

        return ActionResult(
            handled=True,
            reply=friendly_upload_board_start(self.locale) + "\n\n" + friendly_upload_board_need_card(self.locale),
            pending_action=pending,
            client_id=resolved_client,
            upload_options=self._board_upload_options(resolved_client, ready=False),
        )

    async def _continue_upload_board_attachment(
        self,
        pending: PendingChatAction,
        message: str,
        client_id: int | None,
    ) -> ActionResult:
        draft = dict(pending.draft)
        resolved_client = self._resolve_upload_client_id(message, client_id, pending)
        if not resolved_client:
            return ActionResult(
                handled=True,
                reply=friendly_upload_board_need_client(self.locale),
                pending_action=PendingChatAction(action="upload_board_attachment", draft=draft),
            )

        cards = list_board_card_options(self.db, resolved_client)
        card_id = draft.get("card_id") or resolve_board_card_id(message, cards)
        if card_id:
            draft["card_id"] = int(card_id)

        pending = PendingChatAction(
            action="upload_board_attachment",
            client_id=resolved_client,
            draft=draft,
        )

        if not draft.get("card_id"):
            return ActionResult(
                handled=True,
                reply=friendly_upload_board_need_card(self.locale),
                pending_action=pending,
                client_id=resolved_client,
                upload_options=self._board_upload_options(resolved_client, ready=False),
            )

        card_title = next(
            (str(card["title"]) for card in cards if card["id"] == draft["card_id"]),
            str(draft["card_id"]),
        )
        return ActionResult(
            handled=True,
            reply=friendly_upload_board_ready(self.locale, card_title=card_title),
            pending_action=pending,
            client_id=resolved_client,
            upload_options=self._board_upload_options(resolved_client, ready=True),
        )

    def _pending_clients(self) -> list[Client]:
        return list(
            self.db.execute(
                self.clients._scoped_clients_query(self.user, self.merchant_id)
                .options(selectinload(Client.assignments))
                .where(Client.status == ClientStatus.PENDIENTE_DE_REVISION.value)
                .order_by(Client.created_at.asc())
            )
            .scalars()
            .all()
        )

    def _answer_pending_approval_query(self) -> ActionResult:
        pending = self._pending_clients()
        items = [
            {
                "id": client.id,
                "nombre": client.full_name,
                "listo_para_aprobar": len(problems) == 0,
                "problemas_aprobacion": problems,
            }
            for client in pending
            for problems in [validate_approval_requirements(client, self.clients)]
        ]
        return ActionResult(
            handled=True,
            reply=format_pending_approval_answer(self.locale, items),
        )

    def _client_report(self, message: str, client_id: int | None) -> ActionResult:
        builder = ChatbotContextBuilder(self.db, self.user, merchant_id=self.merchant_id)
        resolved = builder.resolve_client_id(message, client_id)
        if not resolved:
            return ActionResult(
                handled=True,
                reply=t(
                    self.locale,
                    "¿De qué cliente quieres el **informe completo**? Dime el **nombre**, **email** o **ID** (ej. #103).",
                    "Which client do you want a **full report** for? Tell me their **name**, **email** or **ID** (e.g. #103).",
                ),
            )
        if not self.clients.user_can_access_client(self.user, resolved):
            return ActionResult(
                handled=True,
                reply=t(
                    self.locale,
                    "No tengo acceso a ese cliente o no lo encontré.",
                    "I don't have access to that client or couldn't find them.",
                ),
            )
        detail = builder._client_detail_payload(resolved)
        if detail.get("error"):
            return ActionResult(handled=True, reply=str(detail["error"]))
        return ActionResult(
            handled=True,
            reply=format_client_report(self.locale, detail),
            client_id=resolved,
        )

    def _resolve_pending_client_id(self, message: str) -> int | None:
        for client in self._pending_clients():
            if client.full_name.lower() in message.lower():
                return client.id
            if client.email.lower() in message.lower():
                return client.id
        id_match = re.search(r"#?(\d+)", message)
        if id_match:
            candidate = int(id_match.group(1))
            client = self.db.get(Client, candidate)
            if client and client.status == ClientStatus.PENDIENTE_DE_REVISION.value:
                return candidate
        return None

    def _list_advisors(self) -> list[User]:
        return list(
            self.db.execute(
                select(User)
                .join(Role)
                .where(Role.code == "ADVISOR", User.is_active.is_(True))
                .order_by(User.first_name, User.last_name)
            )
            .scalars()
            .all()
        )

    def _resolve_advisor(self, message: str) -> User | None:
        advisors = self._list_advisors()
        lowered = message.lower().strip()

        id_match = re.search(r"#?(\d+)", message)
        if id_match:
            advisor_id = int(id_match.group(1))
            for advisor in advisors:
                if advisor.id == advisor_id:
                    return advisor

        for advisor in advisors:
            if advisor.email.lower() in lowered:
                return advisor
            full_name = f"{advisor.first_name} {advisor.last_name}".lower()
            if full_name and full_name in lowered:
                return advisor
            if advisor.first_name.lower() in lowered and advisor.last_name.lower() in lowered:
                return advisor

        if len(advisors) == 1:
            return advisors[0]

        return None

    def _advisor_prompt(self) -> str:
        advisors = self._list_advisors()
        if not advisors:
            return t(
                self.locale,
                "Por ahora no hay asesores activos. Pedile ayuda a un administrador.",
                "There are no active advisors. Please contact an administrator.",
            )
        lines = [f"- **{a.first_name} {a.last_name}** ({a.email})" for a in advisors]
        return friendly_advisor_prompt(self.locale, lines)

    def _strip_contact_data(self, text: str) -> str:
        cleaned = EMAIL_PATTERN.sub("", text)
        cleaned = PHONE_PATTERN.sub("", cleaned)
        cleaned = re.sub(r"[,;]", " ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    def _extract_name_from_message(self, message: str) -> tuple[str | None, str | None]:
        text = message.strip()
        text = NAME_PREFIX_PATTERN.sub("", text, count=1).strip()
        text = self._strip_contact_data(text)

        if not text or not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", text):
            return None, None

        parts = [part for part in text.split() if re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", part)]
        if len(parts) >= 2:
            return parts[0], " ".join(parts[1:])
        if len(parts) == 1:
            return parts[0], None
        return None, None

    def _apply_name_heuristics(self, message: str, merged: dict[str, Any]) -> dict[str, Any]:
        first, last = self._extract_name_from_message(message)
        if looks_like_person_name(first, last):
            if first and not merged.get("first_name"):
                merged["first_name"] = first
            if last and not merged.get("last_name"):
                merged["last_name"] = last
        return merged

    def validate_registration_data(self, client: Client) -> list[str]:
        return validate_approval_requirements(client, self.clients)

    def _verify_pending_clients(self) -> ActionResult:
        pending = self._pending_clients()
        if not pending:
            return ActionResult(
                handled=True,
                reply="No hay clientes pendientes de revisión en este momento.",
            )

        ok_clients: list[str] = []
        bad_clients: list[str] = []

        for client in pending:
            issues = self.validate_registration_data(client)
            label = f"**{client.full_name}** (ID: {client.id}, {client.email})"
            if issues:
                bad_clients.append(f"- {label}\n  - Problemas: {', '.join(issues)}")
            else:
                ok_clients.append(f"- {label}")

        parts = [
            f"## Verificación de clientes pendientes ({len(pending)})\n",
            "_Solo se requieren nombre, email, teléfono, fuente y comercio para aprobar._\n",
            f"✅ **Listos para aprobar:** {len(ok_clients)}",
            f"⚠️ **Con problemas de registro:** {len(bad_clients)}\n",
        ]
        if ok_clients:
            parts.append("### Clientes OK\n" + "\n".join(ok_clients))
        if bad_clients:
            parts.append("\n### Clientes con problemas\n" + "\n".join(bad_clients))

        parts.append(friendly_verify_pending_footer(self.locale))
        return ActionResult(handled=True, reply="\n".join(parts))

    def _list_active_merchants(self) -> list[Merchant]:
        return MerchantContextService(self.db).list_accessible_merchants(self.user)

    async def _extract_registration_fields(self, message: str, draft: dict[str, Any]) -> dict[str, Any]:
        merged = {**draft}
        merchants = self._list_active_merchants()

        email_match = EMAIL_PATTERN.search(message)
        if email_match:
            merged["email"] = email_match.group(0).lower()

        phone_match = PHONE_PATTERN.search(message)
        if phone_match:
            merged["phone"] = re.sub(r"\s+", "", phone_match.group(0))

        source = resolve_source(message)
        if source:
            merged["source"] = source

        merchant_id = resolve_merchant_id(message, merchants)
        if merchant_id:
            merged["merchant_id"] = merchant_id

        merged = self._apply_name_heuristics(message, merged)

        llm = get_llm_service()
        if llm.is_available:
            lang_hint = "español" if not self.locale.lower().startswith("en") else "English"
            merchant_hint = ", ".join(f"{m.name} ({m.code})" for m in merchants) or "ninguno"
            source_hint = ", ".join(s.value for s in ClientSource)
            prompt = (
                f"Extrae datos de registro de cliente del mensaje ({lang_hint}). "
                'Responde SOLO JSON: {"first_name": null, "last_name": null, "email": null, '
                '"phone": null, "source": null, "merchant_id": null}. '
                "Si hay nombre y apellido juntos (ej. Alexis Diaz), separalos en first_name y last_name. "
                f"source debe ser uno de: {source_hint}. "
                f"merchant_id debe ser el id numérico de uno de: {merchant_hint}. "
                f"Mensaje: {message}\nBorrador actual: {json.dumps(draft, ensure_ascii=False)}"
            )
            try:
                raw = await llm.analyze_text(prompt)
                start = raw.find("{")
                end = raw.rfind("}")
                if start >= 0 and end > start:
                    parsed = json.loads(raw[start : end + 1])
                    for key in ("first_name", "last_name", "email", "phone"):
                        value = parsed.get(key)
                        if isinstance(value, str) and value.strip():
                            merged[key] = value.strip()
                    resolved_source = resolve_source(message)
                    if resolved_source:
                        merged["source"] = resolved_source
                    resolved_merchant = resolve_merchant_id(message, merchants)
                    if resolved_merchant:
                        merged["merchant_id"] = resolved_merchant
            except (json.JSONDecodeError, TypeError):
                pass

        return merged

    def _normalize_registration_draft(self, draft: dict[str, Any]) -> dict[str, Any]:
        normalized = {**draft}
        merchant_id = normalized.get("merchant_id")
        if merchant_id is not None:
            try:
                normalized["merchant_id"] = int(merchant_id)
            except (TypeError, ValueError):
                normalized.pop("merchant_id", None)
        source = normalized.get("source")
        if isinstance(source, str) and source.strip():
            code = source.strip().upper()
            if re.fullmatch(r"[A-Z0-9_]+", code):
                normalized["source"] = code
            else:
                normalized.pop("source", None)
        return normalized

    def _missing_registration_fields(self, draft: dict[str, Any]) -> list[str]:
        draft = self._normalize_registration_draft(draft)
        missing: list[str] = []
        for field, label in (
            ("first_name", "nombre"),
            ("last_name", "apellido"),
            ("email", "email"),
            ("phone", "teléfono"),
            ("source", "fuente"),
            ("merchant_id", "comercio"),
        ):
            if not draft.get(field):
                missing.append(label)
        return missing

    def _register_reply(self, draft: dict[str, Any]) -> str:
        return friendly_register_missing(self.locale, draft, self._list_active_merchants())

    async def _start_register_client(self, message: str) -> ActionResult:
        if looks_like_structured_registration_block(message):
            return await self._create_clients_from_bulk(message)

        draft = self._normalize_registration_draft(
            await self._extract_registration_fields(message, {})
        )
        missing = self._missing_registration_fields(draft)
        if missing:
            return ActionResult(
                handled=True,
                reply=self._register_reply(draft),
                pending_action=PendingChatAction(action="register_client", draft=draft),
            )
        return await self._create_client_from_draft(draft)

    async def _continue_register(self, pending: PendingChatAction, message: str) -> ActionResult:
        if looks_like_structured_registration_block(message):
            return await self._create_clients_from_bulk(message)

        draft = self._normalize_registration_draft(
            await self._extract_registration_fields(message, pending.draft)
        )
        missing = self._missing_registration_fields(draft)
        if missing:
            return ActionResult(
                handled=True,
                reply=self._register_reply(draft),
                pending_action=PendingChatAction(action="register_client", draft=draft),
            )
        return await self._create_client_from_draft(draft)

    async def _create_clients_from_bulk(self, message: str) -> ActionResult:
        merchants = self._list_active_merchants()
        blocks = parse_bulk_registration_blocks(message, merchants)

        if not blocks:
            return ActionResult(
                handled=True,
                reply=t(
                    self.locale,
                    "No pude leer clientes en ese formato. Usá bloques con *Datos personales*, *Nombre completo*, *Email*, *Teléfono* y *merchant*.",
                    "I couldn't parse clients from that format. Use blocks with *Personal data*, *Full name*, *Email*, *Phone* and *merchant*.",
                ),
                pending_action=PendingChatAction(action="register_client", draft={}),
            )

        successes: list[tuple[str, int, str, str]] = []
        failures: list[tuple[str, str]] = []

        for block in blocks:
            if block.errors:
                missing = ", ".join(block.errors)
                failures.append(
                    (
                        block.display_name,
                        t(
                            self.locale,
                            f"Faltan datos: {missing}",
                            f"Missing data: {missing}",
                        ),
                    )
                )
                continue

            draft = self._normalize_registration_draft(block.draft)
            missing = self._missing_registration_fields(draft)
            if missing:
                failures.append(
                    (
                        block.display_name,
                        t(
                            self.locale,
                            f"Faltan datos: {', '.join(missing)}",
                            f"Missing data: {', '.join(missing)}",
                        ),
                    )
                )
                continue

            merchant = next((m for m in merchants if m.id == draft.get("merchant_id")), None)
            if merchant is None:
                failures.append(
                    (
                        block.display_name,
                        t(
                            self.locale,
                            "El comercio indicado no es válido o no está activo.",
                            "The selected merchant is invalid or inactive.",
                        ),
                    )
                )
                continue

            try:
                client, _ = self.clients.create_client(
                    actor=self.user,
                    first_name=str(draft["first_name"]),
                    last_name=str(draft["last_name"]),
                    email=str(draft["email"]),
                    phone=str(draft["phone"]),
                    source=str(draft["source"]),
                    merchant_id=int(draft["merchant_id"]),
                )
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                failures.append((block.display_name, detail))
                continue
            except Exception:
                failures.append(
                    (
                        block.display_name,
                        t(
                            self.locale,
                            "No pude guardar el cliente. Intentá de nuevo.",
                            "Could not save the client. Please try again.",
                        ),
                    )
                )
                continue

            verified = self.db.get(Client, client.id)
            if verified is None:
                failures.append(
                    (
                        block.display_name,
                        t(
                            self.locale,
                            "El cliente no se guardó correctamente.",
                            "The client was not saved correctly.",
                        ),
                    )
                )
                continue

            successes.append(
                (verified.full_name, verified.id, verified.email, verified.phone)
            )

        return ActionResult(
            handled=True,
            reply=friendly_bulk_register_result(
                self.locale,
                successes=successes,
                failures=failures,
            ),
            client_id=successes[-1][1] if successes else None,
            pending_action=PendingChatAction(action="register_client", draft={}),
            clients_updated=bool(successes),
        )

    async def _create_client_from_draft(self, draft: dict[str, Any]) -> ActionResult:
        draft = self._normalize_registration_draft(draft)
        missing = self._missing_registration_fields(draft)
        if missing:
            return ActionResult(
                handled=True,
                reply=self._register_reply(draft),
                pending_action=PendingChatAction(action="register_client", draft=draft),
            )

        merchants = self._list_active_merchants()
        merchant = next((m for m in merchants if m.id == draft.get("merchant_id")), None)
        if merchant is None:
            return ActionResult(
                handled=True,
                reply=friendly_register_error(
                    self.locale,
                    t(
                        self.locale,
                        "El comercio indicado no es válido o no está activo.",
                        "The selected merchant is invalid or inactive.",
                    ),
                ),
                pending_action=PendingChatAction(action="register_client", draft=draft),
            )

        try:
            client, _ = self.clients.create_client(
                actor=self.user,
                first_name=str(draft["first_name"]),
                last_name=str(draft["last_name"]),
                email=str(draft["email"]),
                phone=str(draft["phone"]),
                source=str(draft["source"]),
                merchant_id=int(draft["merchant_id"]),
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            return ActionResult(
                handled=True,
                reply=friendly_register_error(self.locale, detail),
                pending_action=PendingChatAction(action="register_client", draft=draft),
            )
        except Exception:
            return ActionResult(
                handled=True,
                reply=friendly_register_error(
                    self.locale,
                    t(
                        self.locale,
                        "No pude guardar el cliente. Intentá de nuevo.",
                        "Could not save the client. Please try again.",
                    ),
                ),
                pending_action=PendingChatAction(action="register_client", draft=draft),
            )

        verified = self.db.get(Client, client.id)
        if verified is None:
            return ActionResult(
                handled=True,
                reply=friendly_register_error(
                    self.locale,
                    t(
                        self.locale,
                        "El cliente no se guardó correctamente. Intentá de nuevo.",
                        "The client was not saved correctly. Please try again.",
                    ),
                ),
                pending_action=PendingChatAction(action="register_client", draft=draft),
            )

        return ActionResult(
            handled=True,
            reply=friendly_register_success(
                self.locale,
                full_name=verified.full_name,
                client_id=verified.id,
                email=verified.email,
                phone=verified.phone,
                source=verified.source,
                merchant_name=merchant.name,
                include_continue_prompt=True,
            ),
            client_id=verified.id,
            pending_action=PendingChatAction(action="register_client", draft={}),
            clients_updated=True,
        )

    async def _start_approve_one(self, client_id: int) -> ActionResult:
        client = self.db.get(Client, client_id)
        if client is None:
            return ActionResult(handled=True, reply=f"No encontré el cliente #{client_id}.")
        if client.status != ClientStatus.PENDIENTE_DE_REVISION.value:
            return ActionResult(
                handled=True,
                reply=f"**{client.full_name}** (#{client.id}) no está pendiente de revisión (estado: {client.status}).",
            )

        issues = self.validate_registration_data(client)
        if issues:
            intro = friendly_approve_one_intro(self.locale, full_name=client.full_name, issues=issues)
            result = self._approve_client(client)
            if result.reply:
                result.reply = f"{intro}\n\n{result.reply}"
            return result
        return self._approve_client(client)

    async def _continue_approve_one(self, pending: PendingChatAction, message: str) -> ActionResult:
        del message
        client = self.db.get(Client, pending.client_id)
        if client is None:
            return ActionResult(handled=True, reply="El cliente ya no existe.", pending_action=None)
        return self._approve_client(client)

    def _approve_client(self, client: Client, advisor_user_id: int | None = None) -> ActionResult:
        del advisor_user_id
        try:
            client, temp_password = self.clients.approve_client(
                actor=self.user,
                client=client,
                send_welcome_notifications=True,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            return ActionResult(handled=True, reply=f"No pude aprobar: **{detail}**")

        approval = ClientApprovalResult(
            client_id=client.id,
            client_name=client.full_name,
            client_email=client.email,
            temp_password=temp_password,
            advisor_name="Pendiente",
        )
        return ActionResult(
            handled=True,
            reply=friendly_approve_success(
                self.locale,
                full_name=client.full_name,
                client_id=client.id,
            ),
            client_id=client.id,
            pending_action=None,
            clients_updated=True,
            client_approval=approval,
            client_approvals=[approval],
        )

    def _start_reject_one(self, client_id: int) -> ActionResult:
        client = self.db.get(Client, client_id)
        if client is None:
            return ActionResult(handled=True, reply=f"No encontré el cliente #{client_id}.")
        if client.status != ClientStatus.PENDIENTE_DE_REVISION.value:
            return ActionResult(
                handled=True,
                reply=f"**{client.full_name}** (#{client.id}) no está pendiente de revisión.",
            )
        return ActionResult(
            handled=True,
            reply=friendly_reject_one_intro(self.locale, full_name=client.full_name),
            pending_action=PendingChatAction(action="reject_client", client_id=client_id),
        )

    def _continue_reject_one(self, pending: PendingChatAction, message: str) -> ActionResult:
        reason = message.strip()
        if len(reason) < 5:
            return ActionResult(
                handled=True,
                reply="El motivo debe tener al menos **5 caracteres**. Intentá de nuevo o escribí `cancelar`.",
                pending_action=pending,
            )

        client = self.db.get(Client, pending.client_id)
        if client is None:
            return ActionResult(handled=True, reply="El cliente ya no existe.", pending_action=None)

        try:
            client = self.clients.reject_client(actor=self.user, client=client, reason=reason)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            return ActionResult(handled=True, reply=f"No pude rechazar: **{detail}**")

        return ActionResult(
            handled=True,
            reply=f"❌ Cliente **{client.full_name}** (#{client.id}) rechazado.\n\nMotivo: {reason}",
            client_id=client.id,
            clients_updated=True,
        )

    async def _start_approve_all(self) -> ActionResult:
        pending = self._pending_clients()
        if not pending:
            return ActionResult(handled=True, reply="No hay clientes pendientes de revisión para aprobar.")
        return self._approve_all(pending)

    async def _continue_approve_all(self, pending: PendingChatAction, message: str) -> ActionResult:
        del message
        clients = [self.db.get(Client, client_id) for client_id in pending.client_ids]
        clients = [client for client in clients if client is not None]
        if clients:
            clients = list(
                self.db.execute(
                    select(Client)
                    .options(selectinload(Client.assignments))
                    .where(Client.id.in_([client.id for client in clients]))
                    .order_by(Client.created_at.asc())
                )
                .scalars()
                .all()
            )
        return self._approve_all(clients)

    def _approve_all(self, clients: list[Client], advisor_user_id: int | None = None) -> ActionResult:
        del advisor_user_id
        approved: list[str] = []
        failed: list[str] = []
        approvals: list[ClientApprovalResult] = []
        last_client_id: int | None = None

        pending_clients = [
            client
            for client in clients
            if client.status == ClientStatus.PENDIENTE_DE_REVISION.value
        ]
        send_welcome_notifications = len(pending_clients) == 1

        successes, bulk_failures = self.clients.bulk_approve_clients(
            actor=self.user,
            clients=clients,
            send_welcome_notifications=send_welcome_notifications,
        )

        for client, temp_password in successes:
            approved.append(f"- **{client.full_name}** (#{client.id})")
            last_client_id = client.id
            approvals.append(
                ClientApprovalResult(
                    client_id=client.id,
                    client_name=client.full_name,
                    client_email=client.email,
                    temp_password=temp_password,
                    advisor_name="Pendiente",
                )
            )

        for client, reason in bulk_failures:
            failed.append(f"- {client.full_name} (#{client.id}): {reason}")

        if len(approved) == 1 and send_welcome_notifications:
            client, _ = successes[0]
            parts = [
                friendly_approve_success(
                    self.locale,
                    full_name=client.full_name,
                    client_id=client.id,
                )
            ]
            if failed:
                parts.append(
                    f"\n\n⚠️ **No aprobados:** {len(failed)}\n" + "\n".join(failed)
                )
        else:
            parts = [f"## Aprobación masiva\n\n✅ **Aprobados:** {len(approved)}"]
            if approved:
                parts.append("\n".join(approved))
            if failed:
                parts.append(
                    f"\n\n⚠️ **No aprobados:** {len(failed)}\n" + "\n".join(failed)
                )
            if approved and len(approved) > 1:
                parts.append(
                    t(
                        self.locale,
                        "\n\n_Los correos y WhatsApp de bienvenida **no se envían** en aprobación masiva. "
                        "Las **contraseñas temporales** quedan disponibles en el detalle de cada cliente aprobado. "
                        "El asesor se asignará al completar datos y documentos._",
                        "\n\n_Welcome emails and WhatsApp are **not sent** on bulk approval. "
                        "**Temporary passwords** are available on each approved client's detail page. "
                        "An advisor will be assigned when data and documents are complete._",
                    )
                )
        return ActionResult(
            handled=True,
            reply="\n".join(parts),
            client_id=last_client_id if len(approved) == 1 else None,
            client_approval=approvals[0] if len(approvals) == 1 else None,
            client_approvals=approvals,
            clients_updated=len(approved) > 0,
        )

    def _start_reject_all(self) -> ActionResult:
        pending = self._pending_clients()
        if not pending:
            return ActionResult(handled=True, reply="No hay clientes pendientes de revisión para rechazar.")
        return ActionResult(
            handled=True,
            reply=(
                f"Hay **{len(pending)}** cliente(s) pendientes.\n\n"
                "Escribí el **motivo del rechazo** para aplicarlo a todos."
            ),
            pending_action=PendingChatAction(
                action="reject_all",
                client_ids=[client.id for client in pending],
            ),
        )

    def _continue_reject_all(self, pending: PendingChatAction, message: str) -> ActionResult:
        reason = message.strip()
        if len(reason) < 5:
            return ActionResult(
                handled=True,
                reply="El motivo debe tener al menos **5 caracteres**.",
                pending_action=pending,
            )

        rejected: list[str] = []
        failed: list[str] = []

        for client_id in pending.client_ids:
            client = self.db.get(Client, client_id)
            if client is None:
                continue
            if client.status != ClientStatus.PENDIENTE_DE_REVISION.value:
                failed.append(f"- #{client_id}: no está pendiente")
                continue
            try:
                client = self.clients.reject_client(actor=self.user, client=client, reason=reason)
                rejected.append(f"- **{client.full_name}** (#{client.id})")
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                failed.append(f"- #{client_id}: {detail}")

        parts = [f"## Rechazo masivo\n\n❌ **Rechazados:** {len(rejected)}"]
        if rejected:
            parts.append("\n".join(rejected))
        if failed:
            parts.append(f"\n\n⚠️ **No rechazados:** {len(failed)}\n" + "\n".join(failed))
        parts.append(f"\n\nMotivo aplicado: {reason}")
        return ActionResult(handled=True, reply="\n".join(parts), clients_updated=len(rejected) > 0)
