from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.chat_conversation import ChatConversation, ChatConversationMessage
from app.models.user import User

MAX_CONVERSATIONS_PER_USER = 20
DEFAULT_LIST_LIMIT = 5
TITLE_MAX_LEN = 80


def _make_title(message: str) -> str:
    clean = " ".join(message.strip().split())
    if not clean:
        return "Nueva conversación"
    if len(clean) <= TITLE_MAX_LEN:
        return clean
    return f"{clean[: TITLE_MAX_LEN - 1].rstrip()}…"


class ChatConversationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_user(self, user: User, *, limit: int = DEFAULT_LIST_LIMIT) -> list[ChatConversation]:
        capped = max(1, min(limit, 20))
        return list(
            self.db.execute(
                select(ChatConversation)
                .where(ChatConversation.user_id == user.id)
                .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())
                .limit(capped)
            )
            .scalars()
            .all()
        )

    def get_for_user(self, user: User, conversation_id: int) -> ChatConversation:
        conversation = self.db.execute(
            select(ChatConversation)
            .options(selectinload(ChatConversation.messages))
            .where(
                ChatConversation.id == conversation_id,
                ChatConversation.user_id == user.id,
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversación no encontrada")
        return conversation

    def create(
        self,
        user: User,
        *,
        title: str | None = None,
        chat_locale: str = "es",
    ) -> ChatConversation:
        conversation = ChatConversation(
            user_id=user.id,
            title=(title or "Nueva conversación")[:120],
            chat_locale=chat_locale if chat_locale in {"es", "en"} else "es",
        )
        self.db.add(conversation)
        self.db.flush()
        self._prune_old_conversations(user.id)
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def resolve_or_create(
        self,
        user: User,
        conversation_id: int | None,
        *,
        first_user_message: str,
        chat_locale: str = "es",
    ) -> ChatConversation:
        if conversation_id is not None:
            return self.get_for_user(user, conversation_id)

        conversation = ChatConversation(
            user_id=user.id,
            title=_make_title(first_user_message),
            chat_locale=chat_locale if chat_locale in {"es", "en"} else "es",
        )
        self.db.add(conversation)
        self.db.flush()
        self._prune_old_conversations(user.id)
        return conversation

    def append_exchange(
        self,
        conversation: ChatConversation,
        *,
        user_message: str | None,
        assistant_reply: str,
        chat_locale: str | None = None,
    ) -> ChatConversation:
        now = datetime.now(timezone.utc)
        if (
            user_message
            and conversation.title in {"", "Nueva conversación"}
            and user_message.strip()
            and user_message.strip() != "."
        ):
            conversation.title = _make_title(user_message)
        if chat_locale in {"es", "en"}:
            conversation.chat_locale = chat_locale
        conversation.updated_at = now
        if user_message and user_message.strip() and user_message.strip() != ".":
            self.db.add(
                ChatConversationMessage(
                    conversation_id=conversation.id,
                    role="user",
                    content=user_message,
                )
            )
        if assistant_reply.strip():
            self.db.add(
                ChatConversationMessage(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=assistant_reply,
                )
            )
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def rename(self, user: User, conversation_id: int, title: str) -> ChatConversation:
        conversation = self.get_for_user(user, conversation_id)
        clean = " ".join(title.strip().split())
        if not clean:
            raise HTTPException(status_code=400, detail="El título no puede estar vacío")
        conversation.title = clean[:120]
        conversation.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def delete_for_user(self, user: User, conversation_id: int) -> None:
        conversation = self.db.execute(
            select(ChatConversation).where(
                ChatConversation.id == conversation_id,
                ChatConversation.user_id == user.id,
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversación no encontrada")
        self.db.delete(conversation)
        self.db.commit()

    def message_counts(self, conversation_ids: list[int]) -> dict[int, int]:
        if not conversation_ids:
            return {}
        rows = self.db.execute(
            select(
                ChatConversationMessage.conversation_id,
                func.count(ChatConversationMessage.id),
            )
            .where(ChatConversationMessage.conversation_id.in_(conversation_ids))
            .group_by(ChatConversationMessage.conversation_id)
        ).all()
        return {int(conversation_id): int(count) for conversation_id, count in rows}

    def _prune_old_conversations(self, user_id: int) -> None:
        ids = list(
            self.db.execute(
                select(ChatConversation.id)
                .where(ChatConversation.user_id == user_id)
                .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())
            )
            .scalars()
            .all()
        )
        stale = ids[MAX_CONVERSATIONS_PER_USER:]
        if not stale:
            return
        self.db.execute(delete(ChatConversation).where(ChatConversation.id.in_(stale)))
