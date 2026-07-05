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
        "upload_document",
        "upload_board_attachment",
        "create_calendly_event",
        "update_calendly_event",
        "cancel_calendly_event",
    ]
    client_id: int | None = None
    client_ids: list[int] = Field(default_factory=list)
    advisor_user_id: int | None = None
    draft: dict[str, Any] = Field(default_factory=dict)


class ClientApprovalResult(BaseModel):
    client_id: int
    client_name: str
    client_email: str
    temp_password: str
    advisor_name: str


class ChatUploadOptions(BaseModel):
    kind: Literal["document", "board_card"]
    document_types: list[dict[str, str]] = Field(default_factory=list)
    board_cards: list[dict[str, Any]] = Field(default_factory=list)
    ready_for_file: bool = False


class ChatCalendlyOptions(BaseModel):
    step: Literal[
        "event_type",
        "date",
        "slot",
        "invitee",
        "events_list",
        "confirm",
    ]
    event_types: list[dict[str, Any]] = Field(default_factory=list)
    slots: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    custom_questions: list[dict[str, Any]] = Field(default_factory=list)
    draft_summary: dict[str, Any] = Field(default_factory=dict)
    ready_to_confirm: bool = False


class ChatCalendlySelection(BaseModel):
    type: Literal[
        "event_type",
        "date",
        "slot",
        "submit_create",
        "submit_update",
        "cancel_event",
        "start_edit",
    ]
    uri: str | None = None
    name: str | None = None
    value: str | None = None
    label: str | None = None
    event_id: int | None = None
    draft: dict[str, Any] = Field(default_factory=dict)
    event_type_uri: str | None = None
    event_type_name: str | None = None
    date: str | None = None
    start_time: str | None = None
    slot_label: str | None = None
    invitee_name: str | None = None
    invitee_email: str | None = None
    custom_questions: list[dict[str, Any]] = Field(default_factory=list)
    questions_and_answers: list[dict[str, Any]] = Field(default_factory=list)


class ChatbotRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=6000)
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=20)
    client_id: int | None = None
    locale: str = "es"
    chat_locale: str | None = None
    pending_action: PendingChatAction | None = None
    calendly_selection: ChatCalendlySelection | None = None


class ChatbotResponse(BaseModel):
    reply: str
    client_id: int | None = None
    pending_action: PendingChatAction | None = None
    chat_locale: str = "es"
    client_approval: ClientApprovalResult | None = None
    client_approvals: list[ClientApprovalResult] = Field(default_factory=list)
    upload_options: ChatUploadOptions | None = None
    calendly_options: ChatCalendlyOptions | None = None
    clients_updated: bool = False
    calendly_updated: bool = False
