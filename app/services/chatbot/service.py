from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.merchant_context import MerchantContextService
from app.models.user import User
from app.core.config import get_settings
from app.schemas.chatbot import ChatHistoryMessage, ChatbotResponse, PendingChatAction
from app.services.chatbot.actions import ChatbotActionHandler
from app.services.chatbot.context import CLIENT_ROLE, SALES_ROLE, STAFF_ROLES, ChatbotContextBuilder
from app.services.chatbot.locale_prefs import is_locale_switch_request, resolve_chat_locale
from app.services.chatbot.messages import (
    friendly_approve_need_advisor,
    friendly_locale_switch,
    friendly_register_missing,
    friendly_reject_need_reason,
    friendly_upload_board_need_card,
    friendly_upload_board_need_client,
    friendly_upload_board_ready,
    friendly_upload_document_need_client,
    friendly_upload_document_need_type,
    friendly_upload_document_ready,
)
from app.services.chatbot.upload_options import document_type_label, list_board_card_options
from app.services.llm import get_llm_service

SYSTEM_PROMPTS = {
    "es": {
        CLIENT_ROLE: """Sos Epoint Bot, un asistente amable del portal de clientes de ePoint CRM.
Hablá SIEMPRE en español rioplatense, cercano y claro (podés tutear).
Ayudás SOLO al cliente autenticado con SU proceso de onboarding.
Usá el contexto JSON. Guiá con pasos simples y enlaces del portal.
Respondé en Markdown. Nunca uses inglés ni formatos técnicos de comandos.""",
        SALES_ROLE: """Sos Epoint Bot, asistente comercial amable de ePoint CRM.
Hablá SIEMPRE en español rioplatense, cercano y claro (podés tutear).
Podés consultar clientes del vendedor y ayudar a registrar nuevos.
Podés registrar **varios clientes seguidos** en la misma conversación: cuando uno queda guardado, pedí los datos del siguiente.
También podés pegar **varios en un solo mensaje** con bloques estructurados (Datos personales / Nombre completo / Email / Teléfono / merchant).
Cada cliente debe tener **email y teléfono únicos**; si hay duplicados, se guardan los que se puedan y se informan los que fallaron.
Si el usuario quiere registrar a alguien, pedí nombre, email, teléfono, fuente y comercio/empresa.
Mostrá las opciones de fuente y comercio disponibles cuando falten esos datos.
Si ya dijo nombre y apellido juntos (ej. "Alexis Diaz"), NO se los vuelvas a pedir.
El sistema ejecuta el registro automáticamente cuando tiene los datos.
Para subir documentos o archivos al tablero, el usuario usa el clip 📎 del chat: primero indica el tipo de documento o la tarjeta, luego adjunta el archivo.
Podés consultar reuniones de Calendly con *mis reuniones de hoy* o *mis reuniones de la semana*.
Podés pedir un **informe completo** de cualquier cliente tuyo (datos, documentos con estado, tablero). Decime el nombre, email o ID.
NUNCA digas que registraste o creaste un cliente: solo el sistema lo hace y confirma con "Ya registré".
Si faltan datos, pedilos. No inventes confirmaciones de éxito.
No hables de documentos, tableros ni onboarding interno.
Respondé en Markdown. Nunca muestres textos en inglés ni formatos tipo "Register client".""",
        "STAFF": """Sos Epoint Bot, asistente interno amable de ePoint CRM (onboarding, asesores, admin).
Hablá SIEMPRE en español rioplatense, profesional pero cercano.
Usá el contexto JSON para informes y seguimiento.

REGLAS DE APROBACIÓN (muy importante):
- Para APROBAR un cliente solo se requieren: nombre completo válido, email válido, teléfono, fuente y comercio.
- Documentos (SSN, licencia, utility bill), datos de perfil (SSN, fecha de nacimiento, dirección, vehículo) y tablero son POST-aprobación.
- Si preguntan por clientes pendientes de aprobación, usá `clientes_pendientes_revision` y `listo_para_aprobar`. NO menciones documentos ni datos de perfil como requisitos para aprobar.
- Si un cliente pendiente tiene `listo_para_aprobar: true`, decí que ya se puede aprobar.

INFORMES:
- Podés pedir un informe completo de un cliente (datos, documentos con estado y motivos, tablero). El sistema lo genera automáticamente.

Si el usuario puede aprobar/rechazar, puede pedirlo en lenguaje natural (aprobar a Juan, aprobar todos, apruébalos todos, verificar pendientes).
Para subir documentos del cliente o adjuntos al tablero, guiá al flujo del clip 📎: tipo de documento o tarjeta, luego archivo.
El sistema ejecuta esas acciones automáticamente ANTES de tu respuesta cuando reconoce la intención.
Si el usuario pide aprobar o rechazar y vos respondés, NO digas que "el sistema va a procesar" ni simules la acción: eso significa que no se ejecutó. Indicá que pruebe por ejemplo *aprobar todos* o *apruebalos todos*.
NUNCA digas que aprobaste o rechazaste un cliente: solo el sistema lo hace y confirma con un mensaje explícito (✅ Cliente aprobado / Aprobación masiva).
No reveles SSN ni credenciales. Respondé en Markdown. Nunca uses inglés ni comandos técnicos rígidos.""",
    },
    "en": {
        CLIENT_ROLE: """You are Epoint Bot, a friendly ePoint CRM client portal assistant.
ALWAYS respond in English. Be warm and clear.
Help ONLY the authenticated client with THEIR onboarding.
Use JSON context. Respond in Markdown.""",
        SALES_ROLE: """You are Epoint Bot, a friendly ePoint CRM sales assistant.
ALWAYS respond in English.
You can register **multiple clients in a row** in the same chat: after each save, ask for the next client's data.
You can also paste **several in one message** using structured blocks (Personal data / Full name / Email / Phone / merchant).
Each client must have a **unique email and phone**; if there are duplicates, save what you can and report failures.
Help register clients naturally. Ask for name, email, phone, source, and merchant/company.
Show available source and merchant options when those fields are missing.
If the user gave first and last name together, do NOT ask again.
Registration runs automatically when data is complete.
You can request a **full client report** (data, documents, board). Say the client name, email or ID.
NEVER say you registered or created a client; only the system does that with an explicit confirmation.
If data is missing, ask for it. Do not invent success confirmations.
Respond in Markdown. Never show rigid command templates.""",
        "STAFF": """You are Epoint Bot, a friendly internal ePoint CRM assistant.
ALWAYS respond in English.
Use JSON context. Natural language actions are executed automatically.

APPROVAL RULES (critical):
- To APPROVE a client you only need: valid full name, email, phone, source and merchant.
- Documents, profile data and board tasks are POST-approval onboarding — NOT approval blockers.
- When asked about pending approvals, use `clientes_pendientes_revision` and `listo_para_aprobar`. Do NOT list documents or profile gaps as approval requirements.

REPORTS:
- Users can request a full client report (data, documents with status/reasons, board). The system generates it automatically.

NEVER say you approved or rejected a client; only the system does that with an explicit confirmation.
Never reveal SSN or credentials. Respond in Markdown.""",
    },
}


class ChatbotService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.llm = get_llm_service()

    async def chat(
        self,
        user: User,
        *,
        message: str,
        history: list[ChatHistoryMessage],
        client_id: int | None,
        locale: str,
        merchant_id: int,
        chat_locale: str | None = None,
        pending_action: PendingChatAction | None = None,
        calendly_selection: dict | None = None,
    ) -> ChatbotResponse:
        effective_locale = resolve_chat_locale(
            message,
            chat_locale=chat_locale,
            fallback_locale=locale,
        )

        if is_locale_switch_request(message):
            reply = friendly_locale_switch(effective_locale)
            if pending_action and pending_action.action == "register_client":
                merchants = MerchantContextService(self.db).list_accessible_merchants(user)
                reply = f"{reply}\n\n{friendly_register_missing(effective_locale, pending_action.draft, merchants)}"
            return ChatbotResponse(
                reply=reply,
                client_id=client_id,
                pending_action=pending_action,
                chat_locale=effective_locale,
            )

        lang = effective_locale
        action_handler = ChatbotActionHandler(
            self.db,
            user,
            locale=effective_locale,
            merchant_id=merchant_id,
        )
        action_result = await action_handler.handle(
            message=message,
            pending_action=pending_action,
            locale=effective_locale,
            client_id=client_id,
            calendly_selection=calendly_selection,
        )
        if action_result and action_result.handled:
            return ChatbotResponse(
                reply=action_result.reply.strip(),
                client_id=action_result.client_id,
                pending_action=action_result.pending_action,
                chat_locale=effective_locale,
                client_approval=action_result.client_approval,
                client_approvals=action_result.client_approvals or [],
                upload_options=action_result.upload_options,
                calendly_options=action_result.calendly_options,
                clients_updated=action_result.clients_updated,
                calendly_updated=action_result.calendly_updated,
            )

        if pending_action and pending_action.action == "register_client":
            merchants = MerchantContextService(self.db).list_accessible_merchants(user)
            return ChatbotResponse(
                reply=friendly_register_missing(effective_locale, pending_action.draft, merchants),
                client_id=client_id,
                pending_action=pending_action,
                chat_locale=effective_locale,
            )

        if pending_action and pending_action.action == "approve_client":
            handler = ChatbotActionHandler(self.db, user, locale=effective_locale, merchant_id=merchant_id)
            return ChatbotResponse(
                reply=f"{friendly_approve_need_advisor(effective_locale)}\n\n{handler._advisor_prompt()}",
                client_id=pending_action.client_id or client_id,
                pending_action=pending_action,
                chat_locale=effective_locale,
            )

        if pending_action and pending_action.action == "approve_all":
            handler = ChatbotActionHandler(self.db, user, locale=effective_locale, merchant_id=merchant_id)
            return ChatbotResponse(
                reply=f"{friendly_approve_need_advisor(effective_locale)}\n\n{handler._advisor_prompt()}",
                client_id=client_id,
                pending_action=pending_action,
                chat_locale=effective_locale,
            )

        if pending_action and pending_action.action == "reject_client":
            return ChatbotResponse(
                reply=friendly_reject_need_reason(effective_locale),
                client_id=pending_action.client_id or client_id,
                pending_action=pending_action,
                chat_locale=effective_locale,
            )

        if pending_action and pending_action.action == "reject_all":
            return ChatbotResponse(
                reply=friendly_reject_need_reason(effective_locale),
                client_id=client_id,
                pending_action=pending_action,
                chat_locale=effective_locale,
            )

        if pending_action and pending_action.action == "upload_document":
            handler = ChatbotActionHandler(self.db, user, locale=effective_locale, merchant_id=merchant_id)
            resolved = pending_action.client_id or client_id
            if not resolved and user.role.code != CLIENT_ROLE:
                resolved = ChatbotContextBuilder(self.db, user, merchant_id=merchant_id).resolve_client_id(message, None)
            if not resolved and user.role.code != CLIENT_ROLE:
                return ChatbotResponse(
                    reply=friendly_upload_document_need_client(effective_locale),
                    client_id=resolved,
                    pending_action=pending_action,
                    chat_locale=effective_locale,
                    upload_options=handler._document_upload_options(ready=False),
                )
            ready = bool(pending_action.draft.get("document_type"))
            return ChatbotResponse(
                reply=friendly_upload_document_need_type(effective_locale)
                if not ready
                else friendly_upload_document_ready(
                    effective_locale,
                    document_label=document_type_label(
                        str(pending_action.draft["document_type"]),
                        effective_locale,
                    ),
                ),
                client_id=resolved,
                pending_action=PendingChatAction(
                    action="upload_document",
                    client_id=resolved,
                    draft=pending_action.draft,
                ),
                chat_locale=effective_locale,
                upload_options=handler._document_upload_options(ready=ready),
            )

        if pending_action and pending_action.action == "upload_board_attachment":
            handler = ChatbotActionHandler(self.db, user, locale=effective_locale, merchant_id=merchant_id)
            resolved = pending_action.client_id or client_id
            if not resolved and user.role.code != CLIENT_ROLE:
                resolved = ChatbotContextBuilder(self.db, user, merchant_id=merchant_id).resolve_client_id(message, None)
            if not resolved and user.role.code != CLIENT_ROLE:
                return ChatbotResponse(
                    reply=friendly_upload_board_need_client(effective_locale),
                    client_id=resolved,
                    pending_action=pending_action,
                    chat_locale=effective_locale,
                )
            ready = bool(pending_action.draft.get("card_id"))
            reply = friendly_upload_board_need_card(effective_locale)
            upload_options = None
            if resolved:
                upload_options = handler._board_upload_options(resolved, ready=ready)
                if ready:
                    cards = list_board_card_options(self.db, resolved)
                    card_title = next(
                        (
                            str(card["title"])
                            for card in cards
                            if card["id"] == pending_action.draft.get("card_id")
                        ),
                        str(pending_action.draft.get("card_id")),
                    )
                    reply = friendly_upload_board_ready(effective_locale, card_title=card_title)
            return ChatbotResponse(
                reply=reply,
                client_id=resolved,
                pending_action=pending_action,
                chat_locale=effective_locale,
                upload_options=upload_options,
            )

        if not self.llm.is_available:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="El asistente no está disponible. Configure GEMINI_API_KEY.",
            )

        builder = ChatbotContextBuilder(self.db, user, merchant_id=merchant_id)
        context_json, resolved_client_id = builder.build(message=message, client_id=client_id)
        system_prompt = self._system_prompt(
            user,
            lang,
            context_json,
            pending_action=pending_action,
        )

        reply = await self.llm.chat(
            system_prompt=system_prompt,
            messages=[{"role": item.role, "content": item.content} for item in history]
            + [{"role": "user", "content": message}],
        )

        return ChatbotResponse(
            reply=reply.strip(),
            client_id=resolved_client_id,
            pending_action=pending_action,
            chat_locale=effective_locale,
        )

    def _system_prompt(
        self,
        user: User,
        lang: str,
        context_json: str,
        *,
        pending_action: PendingChatAction | None,
    ) -> str:
        role = user.role.code
        prompts = SYSTEM_PROMPTS.get(lang, SYSTEM_PROMPTS["es"])

        if role == CLIENT_ROLE:
            base = prompts[CLIENT_ROLE]
        elif role == SALES_ROLE:
            base = prompts[SALES_ROLE]
            if get_settings().calendly_write_enabled:
                base += (
                    "\nTambién podés agendar, cancelar o reprogramar reuniones de Calendly desde el chat "
                    "(*agendar reunión*, *cancelar reunión #ID*, *reprogramar reunión #ID*)."
                    if lang == "es"
                    else "\nYou can also schedule, cancel or reschedule Calendly meetings from chat."
                )
        elif role in STAFF_ROLES:
            base = prompts["STAFF"]
        else:
            base = prompts["STAFF"]

        user_name = f"{user.first_name} {user.last_name}".strip()
        lang_label = "español" if lang == "es" else "English"
        pending_note = ""
        if pending_action:
            pending_note = (
                f"\n\nACCIÓN EN CURSO: {pending_action.action}. "
                f"Datos recolectados: {pending_action.draft}. "
                "Continuá la conversación de forma natural y pedí solo lo que falte."
            )
            if pending_action.action == "register_client":
                pending_note += (
                    "\nNO confirmes que el cliente fue registrado. "
                    "Solo el sistema puede hacerlo cuando los datos estén completos."
                )
            if pending_action.action in ("approve_client", "approve_all"):
                pending_note += (
                    "\nNO confirmes que el cliente fue aprobado. "
                    "Solo el sistema puede hacerlo cuando se asigne el asesor."
                )
            if pending_action.action in ("reject_client", "reject_all"):
                pending_note += (
                    "\nNO confirmes que el cliente fue rechazado. "
                    "Solo el sistema puede hacerlo cuando haya un motivo válido."
                )
            if pending_action.action in ("upload_document", "upload_board_attachment"):
                pending_note += (
                    "\nNO confirmes que el archivo fue subido. "
                    "El usuario debe usar el clip 📎 cuando el sistema indique que está listo."
                )

        return (
            f"{base}{pending_note}\n\n"
            f"IDIOMA OBLIGATORIO DE RESPUESTA: {lang_label}.\n"
            f"Usuario: {user_name} ({user.email})\n"
            f"Rol: {user.role.name} ({role})\n\n"
            f"CONTEXTO ACTUAL (JSON):\n{context_json}"
        )
