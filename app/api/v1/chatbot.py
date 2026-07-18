from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, OptionalActiveMerchantId
from app.schemas.chatbot import ChatbotRequest, ChatbotResponse
from app.services.chatbot import ChatbotService

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])


@router.post("/message", response_model=ChatbotResponse)
async def send_chat_message(
    body: ChatbotRequest,
    current_user: CurrentUser,
    merchant_id: OptionalActiveMerchantId,
    db: DbSession,
) -> ChatbotResponse:
    service = ChatbotService(db)
    return await service.chat(
        current_user,
        message=body.message.strip(),
        history=body.history,
        client_id=body.client_id,
        locale=body.locale,
        merchant_id=merchant_id,
        chat_locale=body.chat_locale,
        pending_action=body.pending_action,
        calendly_selection=body.calendly_selection.model_dump(exclude_none=True) if body.calendly_selection else None,
    )
