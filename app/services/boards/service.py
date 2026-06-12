import json

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.board import Board, BoardTemplate, BoardTemplateCard, BoardTemplateList
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.card_comment import CardComment
from app.models.client import Client
from app.models.enums import NotificationEventType, TaskStatus
from app.models.role import Role
from app.models.user import User
from app.services.notifications import NotificationService


class BoardService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.notifications = NotificationService(db)

    def create_from_template(self, client: Client, template_code: str = "DEFAULT_ONBOARDING") -> Board:
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

        board = Board(client_id=client.id, template_code=template_code)
        self.db.add(board)
        self.db.flush()

        for t_list in sorted(template.template_lists, key=lambda x: x.position):
            bl = BoardList(board_id=board.id, title=t_list.title, position=t_list.position)
            self.db.add(bl)
            self.db.flush()
            for t_card in sorted(t_list.template_cards, key=lambda x: x.position):
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
                    )
                )
        self.db.flush()
        return board

    def get_board_for_client(self, client_id: int) -> Board | None:
        return (
            self.db.execute(
                select(Board)
                .options(
                    joinedload(Board.lists)
                    .joinedload(BoardList.cards)
                    .joinedload(BoardCard.comments)
                    .joinedload(CardComment.author),
                    joinedload(Board.lists).joinedload(BoardList.cards).joinedload(BoardCard.attachments),
                    joinedload(Board.lists)
                    .joinedload(BoardList.cards)
                    .joinedload(BoardCard.credential_submissions),
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
    ):
        from app.models.card_comment import CardComment

        comment = CardComment(
            card_id=card.id,
            author_user_id=author.id,
            body=body.strip(),
            is_internal=is_internal,
        )
        self.db.add(comment)

        portal_user = self.db.execute(
            select(User).where(User.client_id == client.id)
        ).scalar_one_or_none()
        if author.role.code == "CLIENT" and portal_user:
            from app.models.role import Role

            team = list(
                self.db.execute(
                    select(User).join(Role).where(
                        Role.code.in_(["ONBOARDING_MANAGER", "ADVISOR"]),
                        User.is_active.is_(True),
                    )
                ).scalars().all()
            )
            self.notifications.notify(
                event_type=NotificationEventType.TASK_COMMENTED.value,
                users=team,
                title="Nuevo comentario en tarea",
                body=f"Comentario en '{card.title}': {body[:100]}",
                payload={"card_id": card.id, "client_id": client.id},
            )
        elif portal_user:
            self.notifications.notify(
                event_type=NotificationEventType.TASK_COMMENTED.value,
                users=[portal_user],
                title="Nuevo comentario en tu tarea",
                body=f"El equipo comentó en '{card.title}'",
                payload={"card_id": card.id},
            )
        self.db.commit()
        self.db.refresh(comment)
        return comment
