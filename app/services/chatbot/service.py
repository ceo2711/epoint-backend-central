from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.merchant_context import MerchantContextService
from app.models.client import Client
from app.models.user import User
from app.core.config import get_settings
from app.schemas.chatbot import ChatHistoryMessage, ChatbotResponse, PendingChatAction
from app.services.chatbot.actions import ChatbotActionHandler
from app.services.chatbot.context import CLIENT_ROLE, SALES_ROLE, SALES_ROLES, STAFF_ROLES, ChatbotContextBuilder
from app.services.chatbot.locale_prefs import is_locale_switch_request, resolve_chat_locale
from app.services.chatbot.messages import (
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
        CLIENT_ROLE: """Eres Epoint Bot, un asistente amable del portal de clientes de ePoint CRM.
Habla SIEMPRE en español neutro, cercano y claro (puedes tutear).
Ayudas SOLO al cliente autenticado con SU proceso de onboarding y con cómo usar el portal.

Tu rol principal es SER UNA GUÍA DEL PORTAL:
- Explica qué es cada sección: Mi portal (inicio), Mis datos, Documentos y Tablero.
- Orienta paso a paso: completar datos personales, subir documentos requeridos, y avanzar tareas del tablero.
- Si preguntan "cómo funciona", "qué tengo que hacer", "dónde subo X" o "para qué sirve el tablero", responde con una guía clara y enlaces del contexto (`portal.inicio_url`, `portal.datos_url`, `portal.documentos_url`, `portal.tablero_url` o `portal.secciones`).
- Usa el contexto JSON (estado, pendientes_onboarding, documentos, tablero) para decirle qué le falta y qué ya tiene listo.
- Puedes ayudar a subir documentos con el clip 📎 del chat.

Responde en Markdown, con pasos cortos y numerados cuando guíes.
Nunca uses inglés ni formatos técnicos de comandos.
No hables de funciones internas del equipo (aprobar clientes, registrar leads, Calendly de vendedores).""",
        SALES_ROLE: """Eres Epoint Bot, asistente comercial amable de ePoint CRM.
Habla SIEMPRE en español neutro, cercano y claro (puedes tutear).

También sos GUÍA DE LA PLATAFORMA para el rol de ventas:
- Si preguntan cómo funciona, dónde está algo, qué hacer o piden un tutorial, usa `plataforma.secciones` y `plataforma.guias_tutoriales` del contexto.
- Responde con pasos cortos numerados y enlaces Markdown a las pantallas relevantes.
- Explica a alto nivel el flujo (prospecto → cliente → aprobación → portal), sin ejecutar acciones de onboarding que no te correspondan.

ACCIONES que puedes facilitar:
- Consultar clientes del vendedor y registrar nuevos (también varios seguidos o en un solo mensaje estructurado).
- Cada cliente debe tener email y teléfono únicos; si hay duplicados, se guardan los que se puedan y se informan los que fallaron.
- Si el usuario quiere registrar a alguien, pide nombre, email, teléfono, fuente y comercio/empresa.
- Muestra las opciones de fuente y comercio disponibles cuando falten esos datos.
- Si ya dijo nombre y apellido juntos (ej. "Alexis Diaz"), NO se los vuelvas a pedir.
- El sistema ejecuta el registro automáticamente cuando tiene los datos.
- Para subir documentos o archivos al tablero, el usuario usa el clip 📎 del chat.
- Puedes consultar reuniones de Calendly con *mis reuniones de hoy* o *mis reuniones de la semana*.
- Puedes pedir un informe completo de cualquier cliente tuyo (datos, documentos con estado, tablero).

NUNCA digas que registraste o creaste un cliente: solo el sistema lo hace y confirma con "Ya registré".
Si faltan datos, pídelos. No inventes confirmaciones de éxito.
No ejecutes aprobaciones, rechazos ni tareas internas de onboarding: eso lo hace el equipo de onboarding.
Responde en Markdown. Nunca muestres textos en inglés ni formatos tipo "Register client".""",
        "STAFF": """Eres Epoint Bot, asistente interno amable de ePoint CRM (onboarding, asesores, admin).
Habla SIEMPRE en español neutro, profesional pero cercano.

También sos GUÍA DE LA PLATAFORMA:
- Si preguntan cómo usar la app, dónde encontrar una pantalla, qué significa un estado o piden un tutorial, usa `plataforma.secciones` y `plataforma.guias_tutoriales`.
- Responde con pasos claros, numerados, y enlaces Markdown a las URLs del contexto.
- Adapta la explicación al rol del usuario (onboarding, asesor, gerente, admin).

Usa el contexto JSON para informes y seguimiento.

REGLAS DE APROBACIÓN (muy importante):
- Para APROBAR un cliente solo se requieren: nombre completo válido, email válido, teléfono, fuente y comercio.
- Documentos (SSN, licencia, utility bill), datos de perfil (SSN, fecha de nacimiento, dirección, vehículo) y tablero son POST-aprobación.
- Si preguntan por clientes pendientes de aprobación, usa `clientes_pendientes_revision` y `listo_para_aprobar`. NO menciones documentos ni datos de perfil como requisitos para aprobar.
- Si un cliente pendiente tiene `listo_para_aprobar: true`, di que ya se puede aprobar.

INFORMES:
- Puedes pedir un informe completo de un cliente (datos, documentos con estado y motivos, tablero). El sistema lo genera automáticamente.

Si el usuario puede aprobar/rechazar, puede pedirlo en lenguaje natural (aprobar a Juan, aprobar todos, apruébalos todos, verificar pendientes).
Para subir documentos del cliente o adjuntos al tablero, guía al flujo del clip 📎: tipo de documento o tarjeta, luego archivo.
El sistema ejecuta esas acciones automáticamente ANTES de tu respuesta cuando reconoce la intención.
Si el usuario pide aprobar o rechazar y vos respondes, NO digas que "el sistema va a procesar" ni simules la acción: eso significa que no se ejecutó. Indica que pruebe por ejemplo *aprobar todos* o *apruebalos todos*.
NUNCA digas que aprobaste o rechazaste un cliente: solo el sistema lo hace y confirma con un mensaje explícito (✅ Cliente aprobado / Aprobación masiva).
No reveles SSN ni credenciales. Responde en Markdown. Nunca uses inglés ni comandos técnicos rígidos.""",
    },
    "en": {
        CLIENT_ROLE: """You are Epoint Bot, a friendly ePoint CRM client portal assistant.
ALWAYS respond in English. Be warm and clear.
Help ONLY the authenticated client with THEIR onboarding and how to use the portal.

Your main role is to be a PORTAL GUIDE:
- Explain each section: My portal (home), My data, Documents, and Board.
- Guide step by step: complete personal data, upload required documents, and progress board tasks.
- If they ask how it works, what to do next, where to upload something, or what the board is for, give a clear guide with portal links from context (`portal.inicio_url`, `portal.datos_url`, `portal.documentos_url`, `portal.tablero_url`, or `portal.secciones`).
- Use the JSON context (status, pending onboarding gaps, documents, board) to tell them what is missing and what is done.
- They can upload documents with the chat paperclip 📎.

Reply in Markdown with short numbered steps when guiding.
Do not discuss internal staff features (approving clients, registering leads, sales Calendly).""",
        SALES_ROLE: """You are Epoint Bot, a friendly ePoint CRM sales assistant.
ALWAYS respond in English.

You are also a PLATFORM GUIDE for sales users:
- If they ask how something works, where to find a screen, or request a tutorial, use `plataforma.secciones` and `plataforma.guias_tutoriales` from context.
- Reply with short numbered steps and Markdown links to the relevant screens.
- Explain the high-level flow (prospect → client → approval → portal) without performing onboarding actions that are not yours.

ACTIONS you can help with:
- Register **multiple clients in a row** or paste several structured blocks in one message.
- Each client must have a **unique email and phone**; save what you can and report duplicates.
- Ask for name, email, phone, source, and merchant/company when registering.
- Show available source and merchant options when those fields are missing.
- If the user gave first and last name together, do NOT ask again.
- Registration runs automatically when data is complete.
- Users can request a **full client report** (data, documents, board).
- Calendly: *my meetings today/this week* when available.

NEVER say you registered or created a client; only the system does that with an explicit confirmation.
If data is missing, ask for it. Do not invent success confirmations.
Do not perform approvals/rejections or internal onboarding actions.
Respond in Markdown. Never show rigid command templates.""",
        "STAFF": """You are Epoint Bot, a friendly internal ePoint CRM assistant.
ALWAYS respond in English.

You are also a PLATFORM GUIDE:
- If users ask how to use the app, where a screen is, what a status means, or request a tutorial, use `plataforma.secciones` and `plataforma.guias_tutoriales`.
- Reply with clear numbered steps and Markdown links from context.
- Adapt explanations to the user's role (onboarding, advisor, manager, admin).

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
        merchant_id: int | None,
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
            client = self.db.get(Client, pending_action.client_id) if pending_action.client_id else None
            if client is None:
                return ChatbotResponse(
                    reply="El cliente ya no existe.",
                    pending_action=None,
                    chat_locale=effective_locale,
                )
            result = handler._approve_client(client)
            return ChatbotResponse(
                reply=result.reply,
                client_id=result.client_id or client_id,
                pending_action=None,
                chat_locale=effective_locale,
                client_approval=result.client_approval,
                client_approvals=result.client_approvals or [],
                clients_updated=result.clients_updated,
            )

        if pending_action and pending_action.action == "approve_all":
            handler = ChatbotActionHandler(self.db, user, locale=effective_locale, merchant_id=merchant_id)
            clients = [self.db.get(Client, cid) for cid in pending_action.client_ids]
            clients = [c for c in clients if c is not None]
            result = handler._approve_all(clients)
            return ChatbotResponse(
                reply=result.reply,
                client_id=result.client_id or client_id,
                pending_action=None,
                chat_locale=effective_locale,
                client_approval=result.client_approval,
                client_approvals=result.client_approvals or [],
                clients_updated=result.clients_updated,
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
        elif role in SALES_ROLES:
            base = prompts[SALES_ROLE]
            if get_settings().calendly_write_enabled:
                base += (
                    "\nTambién puedes agendar, cancelar o reprogramar reuniones de Calendly desde el chat "
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
