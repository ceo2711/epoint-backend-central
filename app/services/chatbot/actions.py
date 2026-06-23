import json
import re
from dataclasses import dataclass
from typing import Any

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_user_permissions
from app.models.client import Client
from app.models.enums import ClientSource, ClientStatus
from app.models.merchant import Merchant
from app.models.role import Role
from app.models.user import User
from app.schemas.chatbot import PendingChatAction
from app.services.chatbot.registration_options import resolve_merchant_id, resolve_source
from app.services.chatbot.messages import (
    friendly_advisor_prompt,
    friendly_approve_one_intro,
    friendly_cancel,
    friendly_register_error,
    friendly_register_missing,
    friendly_register_success,
    friendly_reject_one_intro,
    friendly_verify_pending_footer,
    t,
)
from app.services.clients import ClientService
from app.services.llm import get_llm_service

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"\+?[\d][\d\s\-()]{7,}[\d]")

CANCEL_PATTERN = re.compile(r"^(cancelar|cancel|no|olvida|olvidalo|detener)\b", re.IGNORECASE)

APPROVE_ONE_PATTERN = re.compile(
    r"aprobar(?:\s+(?:al?\s+)?cliente)?\s+#?(\d+)",
    re.IGNORECASE,
)
REJECT_ONE_PATTERN = re.compile(
    r"rechazar(?:\s+(?:al?\s+)?cliente)?\s+#?(\d+)",
    re.IGNORECASE,
)
APPROVE_ALL_PATTERN = re.compile(
    r"aprobar\s+(?:a\s+)?todos?(?:\s+los?\s+pendientes?)?",
    re.IGNORECASE,
)
REJECT_ALL_PATTERN = re.compile(
    r"rechazar\s+(?:a\s+)?todos?(?:\s+los?\s+pendientes?)?",
    re.IGNORECASE,
)
VERIFY_PENDING_PATTERN = re.compile(
    r"(?:verificar|revisar|validar)(?:\s+los?)?\s+(?:clientes?\s+)?pendientes?",
    re.IGNORECASE,
)
REGISTER_INTENT_PATTERN = re.compile(
    r"(?:quiero\s+)?(?:registrar|crear|agregar|dar\s+de\s+alta|cargar|nuevo|alta\s+de)\b",
    re.IGNORECASE,
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

@dataclass
class ActionResult:
    handled: bool
    reply: str
    pending_action: PendingChatAction | None = None
    client_id: int | None = None


class ChatbotActionHandler:
    def __init__(self, db: Session, user: User, *, locale: str = "es") -> None:
        self.db = db
        self.user = user
        self.locale = locale
        self.clients = ClientService(db)
        self.permissions = set(get_user_permissions(db, user))
        if user.role.code == "ADMIN":
            self.permissions |= {"clients:create", "clients:approve", "clients:read"}

    async def handle(
        self,
        *,
        message: str,
        pending_action: PendingChatAction | None,
        locale: str | None = None,
    ) -> ActionResult | None:
        if locale:
            self.locale = locale

        if CANCEL_PATTERN.match(message.strip()):
            if pending_action:
                return ActionResult(
                    handled=True,
                    reply=friendly_cancel(self.locale),
                    pending_action=None,
                )
            return None

        if pending_action:
            result = await self._continue_pending(pending_action, message)
            if result.handled:
                return result

        return await self._detect_and_run(message)

    async def _detect_and_run(self, message: str) -> ActionResult | None:
        if self._can_create() and REGISTER_INTENT_PATTERN.search(message):
            return await self._start_register_client(message)

        if self._can_approve():
            if VERIFY_PENDING_PATTERN.search(message):
                return self._verify_pending_clients()

            if APPROVE_ALL_PATTERN.search(message):
                return await self._start_approve_all()

            if REJECT_ALL_PATTERN.search(message):
                return self._start_reject_all()

            match = APPROVE_ONE_PATTERN.search(message)
            if match:
                return await self._start_approve_one(int(match.group(1)))

            match = REJECT_ONE_PATTERN.search(message)
            if match:
                return self._start_reject_one(int(match.group(1)))

            if re.search(r"aprobar", message, re.IGNORECASE):
                client_id = self._resolve_pending_client_id(message)
                if client_id:
                    return await self._start_approve_one(client_id)

            if re.search(r"rechazar", message, re.IGNORECASE):
                client_id = self._resolve_pending_client_id(message)
                if client_id:
                    return self._start_reject_one(client_id)

        return None

    async def _continue_pending(self, pending: PendingChatAction, message: str) -> ActionResult:
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
        return ActionResult(handled=False, reply="")

    def _can_create(self) -> bool:
        return "clients:create" in self.permissions

    def _can_approve(self) -> bool:
        return "clients:approve" in self.permissions

    def _pending_clients(self) -> list[Client]:
        return list(
            self.db.execute(
                select(Client)
                .where(Client.status == ClientStatus.PENDIENTE_DE_REVISION.value)
                .order_by(Client.created_at.asc())
            )
            .scalars()
            .all()
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
        if first and not merged.get("first_name"):
            merged["first_name"] = first
        if last and not merged.get("last_name"):
            merged["last_name"] = last
        return merged

    def validate_registration_data(self, client: Client) -> list[str]:
        issues: list[str] = []

        if not client.first_name or not client.first_name.strip():
            issues.append("Nombre vacío")
        if not client.last_name or not client.last_name.strip():
            issues.append("Apellido vacío")
        if not client.email or not client.email.strip():
            issues.append("Email vacío")
        else:
            try:
                validate_email(client.email.strip(), check_deliverability=False)
            except EmailNotValidError:
                issues.append("Email con formato inválido")

        if not client.phone or len(client.phone.strip()) < 5:
            issues.append("Teléfono inválido o muy corto")

        duplicate_email = self.clients.find_client_with_email(client.email, exclude_client_id=client.id)
        if duplicate_email:
            issues.append(f"Email duplicado (cliente #{duplicate_email.id})")

        duplicate_phone = self.clients.find_client_with_phone(client.phone, exclude_client_id=client.id)
        if duplicate_phone:
            issues.append(f"Teléfono duplicado (cliente #{duplicate_phone.id})")

        return issues

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
            f"✅ **Datos correctos:** {len(ok_clients)}",
            f"⚠️ **Con problemas:** {len(bad_clients)}\n",
        ]
        if ok_clients:
            parts.append("### Clientes OK\n" + "\n".join(ok_clients))
        if bad_clients:
            parts.append("\n### Clientes con problemas\n" + "\n".join(bad_clients))

        parts.append(friendly_verify_pending_footer(self.locale))
        return ActionResult(handled=True, reply="\n".join(parts))

    def _list_active_merchants(self) -> list[Merchant]:
        return list(
            self.db.execute(
                select(Merchant).where(Merchant.is_active.is_(True)).order_by(Merchant.name)
            ).scalars().all()
        )

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
                    parsed_source = parsed.get("source")
                    if isinstance(parsed_source, str) and parsed_source.strip():
                        try:
                            merged["source"] = ClientSource(parsed_source.strip().upper()).value
                        except ValueError:
                            resolved = resolve_source(parsed_source)
                            if resolved:
                                merged["source"] = resolved
                    parsed_merchant = parsed.get("merchant_id")
                    if parsed_merchant is not None:
                        try:
                            mid = int(parsed_merchant)
                            if any(m.id == mid for m in merchants):
                                merged["merchant_id"] = mid
                        except (TypeError, ValueError):
                            pass
            except (json.JSONDecodeError, TypeError):
                pass

        return merged

    def _missing_registration_fields(self, draft: dict[str, Any]) -> list[str]:
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
        draft = await self._extract_registration_fields(message, {})
        missing = self._missing_registration_fields(draft)
        if missing:
            return ActionResult(
                handled=True,
                reply=self._register_reply(draft),
                pending_action=PendingChatAction(action="register_client", draft=draft),
            )
        return await self._create_client_from_draft(draft)

    async def _continue_register(self, pending: PendingChatAction, message: str) -> ActionResult:
        draft = await self._extract_registration_fields(message, pending.draft)
        missing = self._missing_registration_fields(draft)
        if missing:
            return ActionResult(
                handled=True,
                reply=self._register_reply(draft),
                pending_action=PendingChatAction(action="register_client", draft=draft),
            )
        return await self._create_client_from_draft(draft)

    async def _create_client_from_draft(self, draft: dict[str, Any]) -> ActionResult:
        merchants = self._list_active_merchants()
        merchant = next((m for m in merchants if m.id == draft.get("merchant_id")), None)
        try:
            client = self.clients.create_client(
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

        return ActionResult(
            handled=True,
            reply=friendly_register_success(
                self.locale,
                full_name=client.full_name,
                client_id=client.id,
                email=client.email,
                phone=client.phone,
                source=client.source,
                merchant_name=merchant.name if merchant else None,
            ),
            client_id=client.id,
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

        advisor = self._resolve_advisor("")
        if advisor is None:
            return ActionResult(
                handled=True,
                reply=friendly_approve_one_intro(self.locale, full_name=client.full_name, issues=issues)
                + "\n\n"
                + self._advisor_prompt(),
                pending_action=PendingChatAction(action="approve_client", client_id=client_id),
            )

        return self._approve_client(client, advisor.id)

    async def _continue_approve_one(self, pending: PendingChatAction, message: str) -> ActionResult:
        client = self.db.get(Client, pending.client_id)
        if client is None:
            return ActionResult(handled=True, reply="El cliente ya no existe.", pending_action=None)

        advisor = self._resolve_advisor(message)
        if advisor is None:
            return ActionResult(
                handled=True,
                reply="No pude identificar el asesor.\n\n" + self._advisor_prompt(),
                pending_action=pending,
            )
        return self._approve_client(client, advisor.id)

    def _approve_client(self, client: Client, advisor_user_id: int) -> ActionResult:
        try:
            client, _temp_password = self.clients.approve_client(
                actor=self.user,
                client=client,
                advisor_user_id=advisor_user_id,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            return ActionResult(handled=True, reply=f"No pude aprobar: **{detail}**")

        advisor = self.db.get(User, advisor_user_id)
        advisor_name = f"{advisor.first_name} {advisor.last_name}" if advisor else str(advisor_user_id)
        return ActionResult(
            handled=True,
            reply=(
                f"✅ Cliente **{client.full_name}** (#{client.id}) aprobado.\n\n"
                f"- Asesor asignado: **{advisor_name}**\n"
                f"- Estado actual: {client.status}\n"
                f"- Se envió bienvenida por email/WhatsApp al cliente."
            ),
            client_id=client.id,
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
        )

    async def _start_approve_all(self) -> ActionResult:
        pending = self._pending_clients()
        if not pending:
            return ActionResult(handled=True, reply="No hay clientes pendientes de revisión para aprobar.")

        advisor = self._resolve_advisor("")
        if advisor is None:
            return ActionResult(
                handled=True,
                reply=(
                    f"Hay **{len(pending)}** cliente(s) pendientes. "
                    + self._advisor_prompt()
                    + "\n\nSe asignará el mismo asesor a todos."
                ),
                pending_action=PendingChatAction(
                    action="approve_all",
                    client_ids=[client.id for client in pending],
                ),
            )
        return self._approve_all(pending, advisor.id)

    async def _continue_approve_all(self, pending: PendingChatAction, message: str) -> ActionResult:
        advisor = self._resolve_advisor(message)
        if advisor is None:
            return ActionResult(
                handled=True,
                reply="No pude identificar el asesor.\n\n" + self._advisor_prompt(),
                pending_action=pending,
            )
        clients = [self.db.get(Client, client_id) for client_id in pending.client_ids]
        clients = [client for client in clients if client is not None]
        return self._approve_all(clients, advisor.id)

    def _approve_all(self, clients: list[Client], advisor_user_id: int) -> ActionResult:
        approved: list[str] = []
        failed: list[str] = []

        for client in clients:
            if client.status != ClientStatus.PENDIENTE_DE_REVISION.value:
                failed.append(f"- {client.full_name} (#{client.id}): no está pendiente")
                continue
            try:
                client, _ = self.clients.approve_client(
                    actor=self.user,
                    client=client,
                    advisor_user_id=advisor_user_id,
                )
                approved.append(f"- **{client.full_name}** (#{client.id})")
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                failed.append(f"- {client.full_name} (#{client.id}): {detail}")

        parts = [f"## Aprobación masiva\n\n✅ **Aprobados:** {len(approved)}"]
        if approved:
            parts.append("\n".join(approved))
        if failed:
            parts.append(f"\n\n⚠️ **No aprobados:** {len(failed)}\n" + "\n".join(failed))
        return ActionResult(handled=True, reply="\n".join(parts))

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
        return ActionResult(handled=True, reply="\n".join(parts))
