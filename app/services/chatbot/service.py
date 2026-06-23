from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.merchant import Merchant
from app.models.user import User
from app.schemas.chatbot import ChatHistoryMessage, ChatbotResponse, PendingChatAction
from app.services.chatbot.actions import ChatbotActionHandler
from app.services.chatbot.context import CLIENT_ROLE, SALES_ROLE, STAFF_ROLES, ChatbotContextBuilder
from app.services.chatbot.locale_prefs import is_locale_switch_request, resolve_chat_locale
from app.services.chatbot.messages import friendly_locale_switch, friendly_register_missing
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
Si el usuario quiere registrar a alguien, pedí nombre, email, teléfono, fuente y comercio/empresa.
Mostrá las opciones de fuente y comercio disponibles cuando falten esos datos.
Si ya dijo nombre y apellido juntos (ej. "Alexis Diaz"), NO se los vuelvas a pedir.
El sistema ejecuta el registro automáticamente cuando tiene los datos.
No hables de documentos, tableros ni onboarding interno.
Respondé en Markdown. Nunca muestres textos en inglés ni formatos tipo "Register client".""",
        "STAFF": """Sos Epoint Bot, asistente interno amable de ePoint CRM (onboarding, asesores, admin).
Hablá SIEMPRE en español rioplatense, profesional pero cercano.
Usá el contexto JSON para informes y seguimiento.
Si el usuario puede aprobar/rechazar, puede pedirlo en lenguaje natural (aprobar a Juan, aprobar todos, verificar pendientes).
El sistema ejecuta esas acciones automáticamente.
No reveles SSN ni credenciales. Respondé en Markdown. Nunca uses inglés ni comandos técnicos rígidos.""",
    },
    "en": {
        CLIENT_ROLE: """You are Epoint Bot, a friendly ePoint CRM client portal assistant.
ALWAYS respond in English. Be warm and clear.
Help ONLY the authenticated client with THEIR onboarding.
Use JSON context. Respond in Markdown.""",
        SALES_ROLE: """You are Epoint Bot, a friendly ePoint CRM sales assistant.
ALWAYS respond in English.
Help register clients naturally. Ask for name, email, phone, source, and merchant/company.
Show available source and merchant options when those fields are missing.
If the user gave first and last name together, do NOT ask again.
Registration runs automatically when data is complete.
Respond in Markdown. Never show rigid command templates.""",
        "STAFF": """You are Epoint Bot, a friendly internal ePoint CRM assistant.
ALWAYS respond in English.
Use JSON context. Natural language actions are executed automatically.
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
        chat_locale: str | None = None,
        pending_action: PendingChatAction | None = None,
    ) -> ChatbotResponse:
        effective_locale = resolve_chat_locale(
            message,
            chat_locale=chat_locale,
            fallback_locale=locale,
        )

        if is_locale_switch_request(message):
            reply = friendly_locale_switch(effective_locale)
            if pending_action and pending_action.action == "register_client":
                merchants = list(
                    self.db.execute(
                        select(Merchant).where(Merchant.is_active.is_(True)).order_by(Merchant.name)
                    ).scalars().all()
                )
                reply = f"{reply}\n\n{friendly_register_missing(effective_locale, pending_action.draft, merchants)}"
            return ChatbotResponse(
                reply=reply,
                client_id=client_id,
                pending_action=pending_action,
                chat_locale=effective_locale,
            )

        lang = effective_locale
        action_handler = ChatbotActionHandler(self.db, user, locale=effective_locale)
        action_result = await action_handler.handle(
            message=message,
            pending_action=pending_action,
            locale=effective_locale,
        )
        if action_result and action_result.handled:
            return ChatbotResponse(
                reply=action_result.reply.strip(),
                client_id=action_result.client_id,
                pending_action=action_result.pending_action,
                chat_locale=effective_locale,
            )

        if not self.llm.is_available:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="El asistente no está disponible. Configure GEMINI_API_KEY.",
            )

        builder = ChatbotContextBuilder(self.db, user)
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

        return (
            f"{base}{pending_note}\n\n"
            f"IDIOMA OBLIGATORIO DE RESPUESTA: {lang_label}.\n"
            f"Usuario: {user_name} ({user.email})\n"
            f"Rol: {user.role.name} ({role})\n\n"
            f"CONTEXTO ACTUAL (JSON):\n{context_json}"
        )
