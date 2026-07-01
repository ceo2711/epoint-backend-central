from dataclasses import dataclass

from app.schemas.chatbot import (
    ChatCalendlyOptions,
    ChatUploadOptions,
    ClientApprovalResult,
    PendingChatAction,
)


@dataclass
class ActionResult:
    handled: bool
    reply: str
    pending_action: PendingChatAction | None = None
    client_id: int | None = None
    client_approval: ClientApprovalResult | None = None
    client_approvals: list[ClientApprovalResult] | None = None
    upload_options: ChatUploadOptions | None = None
    calendly_options: ChatCalendlyOptions | None = None
    clients_updated: bool = False
    calendly_updated: bool = False
