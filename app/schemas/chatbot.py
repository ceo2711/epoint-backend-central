from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=8000)


class PendingChatAction(BaseModel):
    action: Literal[
        "register_client",
        "approve_client",
        "reject_client",
        "approve_all",
        "reject_all",
    ]
    client_id: int | None = None
    client_ids: list[int] = Field(default_factory=list)
    advisor_user_id: int | None = None
    draft: dict[str, Any] = Field(default_factory=dict)


class ChatbotRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=20)
    client_id: int | None = None
    locale: str = "es"
    chat_locale: str | None = None
    pending_action: PendingChatAction | None = None


class ChatbotResponse(BaseModel):
    reply: str
    client_id: int | None = None
    pending_action: PendingChatAction | None = None
    chat_locale: str = "es"
