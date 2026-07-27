from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, OptionalActiveMerchantId
from app.schemas.chatbot import (
    ChatConversationCreate,
    ChatConversationDetail,
    ChatConversationMessageOut,
    ChatConversationSummary,
    ChatConversationUpdate,
    ChatbotRequest,
    ChatbotResponse,
)
from app.schemas.common import MessageResponse
from app.services.chat_conversations import ChatConversationService
from app.services.chatbot import ChatbotService

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])


def _summary(conversation, message_count: int = 0) -> ChatConversationSummary:
    return ChatConversationSummary(
        id=conversation.id,
        title=conversation.title,
        chat_locale=conversation.chat_locale,
        message_count=message_count,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _detail(conversation) -> ChatConversationDetail:
    return ChatConversationDetail(
        id=conversation.id,
        title=conversation.title,
        chat_locale=conversation.chat_locale,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            ChatConversationMessageOut(
                id=message.id,
                role=message.role,  # type: ignore[arg-type]
                content=message.content,
                created_at=message.created_at,
            )
            for message in conversation.messages
            if message.role in {"user", "assistant"}
        ],
    )


@router.get("/conversations", response_model=list[ChatConversationSummary])
def list_conversations(
    current_user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=5, ge=1, le=20),
) -> list[ChatConversationSummary]:
    service = ChatConversationService(db)
    conversations = service.list_for_user(current_user, limit=limit)
    counts = service.message_counts([item.id for item in conversations])
    return [_summary(item, counts.get(item.id, 0)) for item in conversations]


@router.post("/conversations", response_model=ChatConversationDetail, status_code=201)
def create_conversation(
    body: ChatConversationCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> ChatConversationDetail:
    service = ChatConversationService(db)
    conversation = service.create(
        current_user,
        chat_locale=body.chat_locale or "es",
    )
    return _detail(conversation)


@router.get("/conversations/{conversation_id}", response_model=ChatConversationDetail)
def get_conversation(
    conversation_id: int,
    current_user: CurrentUser,
    db: DbSession,
) -> ChatConversationDetail:
    service = ChatConversationService(db)
    conversation = service.get_for_user(current_user, conversation_id)
    return _detail(conversation)


@router.patch("/conversations/{conversation_id}", response_model=ChatConversationSummary)
def update_conversation(
    conversation_id: int,
    body: ChatConversationUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> ChatConversationSummary:
    service = ChatConversationService(db)
    conversation = service.rename(current_user, conversation_id, body.title)
    counts = service.message_counts([conversation.id])
    return _summary(conversation, counts.get(conversation.id, 0))


@router.delete("/conversations/{conversation_id}", response_model=MessageResponse)
def delete_conversation(
    conversation_id: int,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageResponse:
    ChatConversationService(db).delete_for_user(current_user, conversation_id)
    return MessageResponse(message="Conversación eliminada")


@router.post("/message", response_model=ChatbotResponse)
async def send_chat_message(
    body: ChatbotRequest,
    current_user: CurrentUser,
    merchant_id: OptionalActiveMerchantId,
    db: DbSession,
) -> ChatbotResponse:
    conversations = ChatConversationService(db)
    conversation = conversations.resolve_or_create(
        current_user,
        body.conversation_id,
        first_user_message=body.message.strip(),
        chat_locale=body.chat_locale or "es",
    )

    service = ChatbotService(db)
    response = await service.chat(
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

    conversations.append_exchange(
        conversation,
        user_message=body.message.strip(),
        assistant_reply=response.reply,
        chat_locale=response.chat_locale,
    )
    response.conversation_id = conversation.id
    return response
