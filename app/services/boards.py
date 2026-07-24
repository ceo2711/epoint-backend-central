import json
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.board import Board, BoardTemplate, BoardTemplateCard, BoardTemplateList
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.card_attachment import CardAttachment
from app.models.card_attachment_verification import CardAttachmentVerification
from app.models.card_comment import CardComment
from app.models.client import Client
from app.models.enums import BoardCardLabel, DocumentVerificationStatus, NotificationEventType, TaskStatus
from app.models.role import Role
from app.models.user import User
from app.services.default_board_cards import (
    apply_default_cards_to_board_list,
    refresh_dynamic_card_descriptions,
)
from app.services.notifications import NotificationService
from app.services.storage import get_storage_provider
from app.utils.mime import ALLOWED_MIME_TYPES, resolve_content_type


class BoardService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.notifications = NotificationService(db)

    def get_active_template(self, template_code: str = "DEFAULT_ONBOARDING") -> BoardTemplate:
        template = (
            self.db.execute(
                select(BoardTemplate)
                .options(
                    joinedload(BoardTemplate.template_lists).joinedload(BoardTemplateList.template_cards)
                )
                .where(BoardTemplate.code == template_code, BoardTemplate.is_active.is_(True))
            )
            .unique()
            .scalar_one_or_none()
        )
        if template is None:
            raise ValueError(f"Template {template_code} no encontrado")
        return template

    def create_from_template(
        self,
        client: Client,
        template_code: str = "DEFAULT_ONBOARDING",
        *,
        template: BoardTemplate | None = None,
    ) -> Board:
        if template is None:
            template = self.get_active_template(template_code)

        board = Board(client_id=client.id, template_code=template_code)
        self.db.add(board)
        self.db.flush()

        for t_list in sorted(template.template_lists, key=lambda x: x.position):
            bl = BoardList(board_id=board.id, title=t_list.title, position=t_list.position)
            self.db.add(bl)
            self.db.flush()
            template_cards = sorted(t_list.template_cards, key=lambda x: x.position)
            if template_cards:
                for t_card in template_cards:
                    self.db.add(
                        BoardCard(
                            list_id=bl.id,
                            title=t_card.title,
                            description_md=t_card.description_md,
                            instructions_md=t_card.instructions_md,
                            external_links=t_card.external_links,
                            position=t_card.position,
                            requires_credentials=t_card.requires_credentials,
                            requires_file_upload=t_card.requires_file_upload,
                            status=TaskStatus.PENDIENTE.value,
                            label=BoardCardLabel.PENDIENTE.value,
                        )
                    )
            else:
                apply_default_cards_to_board_list(self.db, board_list=bl, client=client)
        self.db.flush()
        board_lists = list(
            self.db.execute(
                select(BoardList)
                .options(selectinload(BoardList.cards))
                .where(BoardList.board_id == board.id)
                .order_by(BoardList.position)
            ).scalars().all()
        )
        refresh_dynamic_card_descriptions(self.db, board_lists=board_lists, client=client)
        self.db.flush()
        return board

    def get_board_for_client(self, client_id: int) -> Board | None:
        return (
            self.db.execute(
                select(Board)
                .options(
                    selectinload(Board.lists)
                    .selectinload(BoardList.cards)
                    .selectinload(BoardCard.comments)
                    .selectinload(CardComment.author),
                    selectinload(Board.lists)
                    .selectinload(BoardList.cards)
                    .selectinload(BoardCard.attachments)
                    .selectinload(CardAttachment.uploaded_by),
                    selectinload(Board.lists)
                    .selectinload(BoardList.cards)
                    .selectinload(BoardCard.credential_submissions),
                )
                .where(Board.client_id == client_id)
            )
            .unique()
            .scalar_one_or_none()
        )

    def update_card_status(
        self,
        *,
        card: BoardCard,
        status: str,
        actor: User,
        client: Client,
    ) -> BoardCard:
        card.status = status
        if status == TaskStatus.COMPLETADA.value:
            portal_user = self.db.execute(
                select(User).join(Role).where(User.client_id == client.id, Role.code == "CLIENT")
            ).scalar_one_or_none()
            recipients: list[User] = []
            if actor.role.code == "CLIENT" and portal_user:
                from app.models.role import Role

                team = self.db.execute(
                    select(User).join(Role).where(
                        Role.code.in_(["ONBOARDING_MANAGER", "ADVISOR"]),
                        User.is_active.is_(True),
                    )
                ).scalars().all()
                recipients = list(team)
            elif portal_user:
                recipients = [portal_user]
            if recipients:
                self.notifications.notify(
                    event_type=NotificationEventType.TASK_COMPLETED.value,
                    users=recipients,
                    title="Tarea completada",
                    body=f"La tarea '{card.title}' fue marcada como completada.",
                    payload={"card_id": card.id, "client_id": client.id},
                )
        self.db.commit()
        self.db.refresh(card)
        return card

    def add_comment(
        self,
        *,
        card: BoardCard,
        author: User,
        body: str,
        is_internal: bool,
        client: Client,
        attachments: list[tuple[str, str, bytes]] | None = None,
    ):
        from app.models.card_comment import CardComment

        clean_body = body.strip()
        files = attachments or []
        if not clean_body and not files:
            raise ValueError("El comentario o al menos un archivo es obligatorio")

        comment = CardComment(
            card_id=card.id,
            author_user_id=author.id,
            body=clean_body,
            is_internal=is_internal,
        )
        self.db.add(comment)
        self.db.flush()

        stored_attachments: list[CardAttachment] = []
        for filename, content_type, file_bytes in files:
            stored_attachments.append(
                self._create_attachment(
                    card=card,
                    actor=author,
                    client=client,
                    filename=filename,
                    content_type=content_type,
                    file_bytes=file_bytes,
                    comment_id=comment.id,
                )
            )

        self._notify_comment(
            card=card,
            author=author,
            client=client,
            body=clean_body,
            is_internal=is_internal,
        )
        self.db.commit()
        self.db.refresh(comment)
        for attachment in stored_attachments:
            self.db.refresh(attachment)
            if attachment.verification_status:
                self._queue_attachment_verification(attachment)
        return comment

    def _notify_comment(
        self,
        *,
        card: BoardCard,
        author: User,
        client: Client,
        body: str,
        is_internal: bool,
    ) -> None:
        from app.services.clients import ClientService
        from app.utils.comment_mentions import extract_mention_user_ids, format_comment_preview

        mentioned_users = ClientService(self.db).validate_mention_user_ids(
            client=client,
            current_user=author,
            user_ids=extract_mention_user_ids(body),
            is_internal=is_internal,
        )
        explicit_mention_ids = {user.id for user in mentioned_users if user.id != author.id}

        recipients = self._comment_notification_recipients(
            client=client,
            author=author,
            is_internal=is_internal,
        )
        seen = {user.id for user in recipients}
        for user in mentioned_users:
            if user.id != author.id and user.id not in seen:
                seen.add(user.id)
                recipients.append(user)
        recipients = [
            user
            for user in recipients
            if user.role.code != "ONBOARDING_MANAGER" or user.id in explicit_mention_ids
        ]
        if not recipients:
            return

        preview = format_comment_preview(body) if body else "(archivos adjuntos)"
        self.notifications.notify(
            event_type=NotificationEventType.TASK_COMMENTED.value,
            users=recipients,
            title="Nuevo comentario en tarea",
            body=f"Comentario en '{card.title}': {preview}",
            payload={"card_id": card.id, "client_id": client.id},
        )

    def _comment_notification_recipients(
        self,
        *,
        client: Client,
        author: User,
        is_internal: bool,
    ) -> list[User]:
        from app.services.clients import ClientService

        client_service = ClientService(self.db)
        portal_user = self.db.execute(
            select(User).join(Role).where(User.client_id == client.id, Role.code == "CLIENT")
        ).scalar_one_or_none()
        advisor = client_service._get_active_advisor(client)

        recipients: list[User] = []
        role = author.role.code

        if is_internal:
            if role == "ONBOARDING_MANAGER" and advisor:
                recipients = [advisor]
        elif role == "CLIENT":
            if advisor:
                recipients = [advisor]
        elif role == "ADVISOR":
            if portal_user:
                recipients = [portal_user]
        elif role == "ONBOARDING_MANAGER":
            if portal_user:
                recipients.append(portal_user)
            if advisor:
                recipients.append(advisor)
        else:
            if portal_user:
                recipients.append(portal_user)
            if advisor:
                recipients.append(advisor)

        seen: set[int] = set()
        unique: list[User] = []
        for user in recipients:
            if user and user.id != author.id and user.id not in seen:
                seen.add(user.id)
                unique.append(user)
        return unique

    def move_card(
        self,
        *,
        card: BoardCard,
        target_list_id: int,
        target_position: int,
    ) -> BoardCard:
        board = card.board_list.board
        target_list = self.db.get(BoardList, target_list_id)
        if target_list is None or target_list.board_id != board.id:
            raise ValueError("Lista destino inválida")

        source_list_id = card.list_id
        source_cards = [
            item
            for item in sorted(card.board_list.cards, key=lambda row: row.position)
            if item.id != card.id
        ]
        target_cards = [
            item
            for item in sorted(target_list.cards, key=lambda row: row.position)
            if item.id != card.id
        ]

        card.list_id = target_list_id
        insert_at = max(0, min(target_position, len(target_cards)))
        target_cards.insert(insert_at, card)

        for index, item in enumerate(source_cards):
            item.position = index
        for index, item in enumerate(target_cards):
            item.position = index

        from app.models.client import Client
        from app.services.client_onboarding_status import sync_client_onboarding_status

        client = self.db.get(Client, board.client_id)
        if client is not None:
            sync_client_onboarding_status(self.db, client)

        self.db.commit()
        self.db.refresh(card)
        return card

    def create_card(
        self,
        *,
        board_list: BoardList,
        title: str,
        position: int | None = None,
    ) -> BoardCard:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("El título es obligatorio")

        target_cards = sorted(board_list.cards, key=lambda row: row.position)
        insert_at = len(target_cards) if position is None else max(0, min(position, len(target_cards)))

        new_card = BoardCard(
            list_id=board_list.id,
            title=clean_title,
            status=TaskStatus.PENDIENTE.value,
            label=BoardCardLabel.PENDIENTE.value,
            position=insert_at,
        )
        self.db.add(new_card)
        self.db.flush()

        ordered = [item for item in sorted(board_list.cards, key=lambda row: row.position) if item.id != new_card.id]
        ordered.insert(insert_at, new_card)
        for index, item in enumerate(ordered):
            item.position = index

        self.db.commit()
        self.db.refresh(new_card)
        return new_card

    def delete_card(self, *, card: BoardCard) -> None:
        board = card.board_list.board
        list_id = card.list_id
        card_id = card.id
        self.db.execute(delete(BoardCard).where(BoardCard.id == card_id))
        self.db.flush()

        remaining = (
            self.db.execute(
                select(BoardCard)
                .where(BoardCard.list_id == list_id)
                .order_by(BoardCard.position)
            )
            .scalars()
            .all()
        )
        for index, item in enumerate(remaining):
            item.position = index

        from app.services.client_onboarding_status import sync_client_onboarding_status

        client = self.db.get(Client, board.client_id)
        if client is not None:
            sync_client_onboarding_status(self.db, client)

        self.db.commit()

    def update_card(
        self,
        *,
        card: BoardCard,
        title: str | None = None,
        description_md: str | None = None,
    ) -> BoardCard:
        if title is not None:
            clean_title = title.strip()
            if not clean_title:
                raise ValueError("El título es obligatorio")
            card.title = clean_title
        if description_md is not None:
            card.description_md = description_md.strip() or None
        self.db.commit()
        self.db.refresh(card)
        return card

    def update_card_label(self, *, card: BoardCard, label: str | None) -> BoardCard:
        card.label = label
        self.db.commit()
        self.db.refresh(card)
        return card

    def upload_attachment(
        self,
        *,
        card: BoardCard,
        actor: User,
        client: Client,
        filename: str,
        content_type: str,
        file_bytes: bytes,
        attachment_type: str = "CLIENT_UPLOAD",
        comment_id: int | None = None,
    ) -> CardAttachment:
        attachment = self._create_attachment(
            card=card,
            actor=actor,
            client=client,
            filename=filename,
            content_type=content_type,
            file_bytes=file_bytes,
            attachment_type=attachment_type,
            comment_id=comment_id,
        )
        self.db.commit()
        self.db.refresh(attachment)
        if attachment.verification_status:
            self._queue_attachment_verification(attachment)
        return attachment

    def _should_verify_attachment(self, *, card: BoardCard, actor: User) -> bool:
        if actor.role.code == "CLIENT":
            return True
        return card.requires_file_upload

    def _queue_attachment_verification(self, attachment: CardAttachment) -> None:
        attachment.verification_status = DocumentVerificationStatus.EN_PROCESO.value
        self.db.commit()
        from app.workers.enqueue import enqueue_card_attachment_verification

        enqueue_card_attachment_verification(attachment.id)

    def load_latest_attachment_verifications_map(
        self, attachment_ids: list[int]
    ) -> dict[int, CardAttachmentVerification]:
        if not attachment_ids:
            return {}

        latest_per_attachment = (
            select(
                CardAttachmentVerification.attachment_id,
                func.max(CardAttachmentVerification.verified_at).label("verified_at"),
            )
            .where(CardAttachmentVerification.attachment_id.in_(attachment_ids))
            .group_by(CardAttachmentVerification.attachment_id)
            .subquery()
        )
        rows = (
            self.db.execute(
                select(CardAttachmentVerification)
                .join(
                    latest_per_attachment,
                    (CardAttachmentVerification.attachment_id == latest_per_attachment.c.attachment_id)
                    & (CardAttachmentVerification.verified_at == latest_per_attachment.c.verified_at),
                )
            )
            .scalars()
            .all()
        )
        return {row.attachment_id: row for row in rows}

    def latest_attachment_verification_messages(
        self,
        attachment: CardAttachment,
        *,
        latest_verification: CardAttachmentVerification | None = None,
    ) -> tuple["LocalizedStringList | None", "LocalizedStringList | None"]:
        from app.schemas.client import LocalizedStringList
        from app.services.document_verification_messages import (
            normalize_bilingual_messages,
            to_localized_lists,
        )

        if not attachment.verification_status or attachment.verification_status not in {
            DocumentVerificationStatus.RECHAZADO.value,
            DocumentVerificationStatus.APROBADO.value,
        }:
            return None, None

        latest = latest_verification
        if latest is None:
            latest = self.db.execute(
                select(CardAttachmentVerification)
                .where(CardAttachmentVerification.attachment_id == attachment.id)
                .order_by(CardAttachmentVerification.verified_at.desc())
                .limit(1)
            ).scalar_one_or_none()

        if latest is None:
            return None, None

        rejection = None
        approval = None

        if attachment.verification_status == DocumentVerificationStatus.RECHAZADO.value:
            rejection_items = normalize_bilingual_messages(latest.rejection_reasons)
            if rejection_items:
                rejection = LocalizedStringList(**to_localized_lists(rejection_items))
        else:
            approval_items = normalize_bilingual_messages(latest.approval_reasons)
            if approval_items:
                approval = LocalizedStringList(**to_localized_lists(approval_items))

        return rejection, approval

    def _create_attachment(
        self,
        *,
        card: BoardCard,
        actor: User,
        client: Client,
        filename: str,
        content_type: str,
        file_bytes: bytes,
        attachment_type: str = "CLIENT_UPLOAD",
        comment_id: int | None = None,
    ) -> CardAttachment:
        if not file_bytes:
            raise ValueError("El archivo está vacío")

        if comment_id is not None:
            comment = self.db.get(CardComment, comment_id)
            if comment is None or comment.card_id != card.id:
                raise ValueError("Comentario inválido")

        mime_type = resolve_content_type(content_type, filename)
        if mime_type not in ALLOWED_MIME_TYPES:
            raise ValueError("Tipo de archivo no permitido")

        ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
        storage = get_storage_provider()
        key = storage.build_key(
            "clients",
            str(client.id),
            "board",
            "cards",
            str(card.id),
            f"{uuid.uuid4()}.{ext}",
        )
        storage.put_object(key, file_bytes, mime_type)

        attachment = CardAttachment(
            card_id=card.id,
            comment_id=comment_id,
            type=attachment_type,
            storage_key=key,
            original_filename=filename,
            mime_type=mime_type,
            uploaded_by_user_id=actor.id,
        )
        if self._should_verify_attachment(card=card, actor=actor):
            attachment.verification_status = DocumentVerificationStatus.PENDIENTE.value
        self.db.add(attachment)
        attachment.uploaded_by = actor
        return attachment
