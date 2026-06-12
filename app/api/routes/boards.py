from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_permissions
from app.core.encryption import encrypt_value
from app.models.board_card import BoardCard
from app.models.card_attachment import CardAttachment
from app.models.client import Client
from app.models.credential_submission import CredentialSubmission
from app.models.user import User
from app.schemas.board import (
    BoardCardResponse,
    BoardListResponse,
    BoardResponse,
    CardAttachmentResponse,
    CardCommentCreate,
    CardCommentResponse,
    CardResultUpdate,
    CardStatusUpdate,
    CredentialSubmit,
)
from app.schemas.common import MessageResponse
from app.services.audit import AuditService
from app.services.boards import BoardService
from app.services.clients import ClientService
from app.services.storage import get_storage_provider

router = APIRouter(prefix="/boards", tags=["Tableros"])


def _build_board_response(board, storage, user: User) -> BoardResponse:
    lists = []
    for bl in sorted(board.lists, key=lambda x: x.position):
        cards = []
        for card in sorted(bl.cards, key=lambda x: x.position):
            comments = [
                CardCommentResponse(
                    id=c.id,
                    body=c.body,
                    is_internal=c.is_internal,
                    author_name=c.author.full_name if c.author else "—",
                    created_at=c.created_at,
                )
                for c in card.comments
                if not c.is_internal or user.role.code != "CLIENT"
            ]
            attachments = [
                CardAttachmentResponse(
                    id=a.id,
                    type=a.type,
                    original_filename=a.original_filename,
                    download_url=storage.generate_download_url(a.storage_key),
                )
                for a in card.attachments
            ]
            cards.append(
                BoardCardResponse(
                    id=card.id,
                    title=card.title,
                    description_md=card.description_md,
                    instructions_md=card.instructions_md,
                    external_links=card.external_links,
                    status=card.status,
                    position=card.position,
                    requires_credentials=card.requires_credentials,
                    requires_file_upload=card.requires_file_upload,
                    client_result_text=card.client_result_text,
                    comments=comments,
                    attachments=attachments,
                    has_credentials=len(card.credential_submissions) > 0,
                )
            )
        lists.append(BoardListResponse(id=bl.id, title=bl.title, position=bl.position, cards=cards))
    return BoardResponse(id=board.id, client_id=board.client_id, template_code=board.template_code, lists=lists)


@router.get("/client/{client_id}", response_model=BoardResponse)
def get_board(
    client_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> BoardResponse:
    if current_user.role.code == "CLIENT" and current_user.client_id != client_id:
        raise HTTPException(status_code=403)
    if current_user.role.code != "CLIENT":
        cs = ClientService(db)
        if cs.get_client_for_user(current_user, client_id) is None:
            raise HTTPException(status_code=404)
    board_service = BoardService(db)
    board = board_service.get_board_for_client(client_id)
    if board is None:
        raise HTTPException(status_code=404, detail="Tablero no encontrado")
    return _build_board_response(board, get_storage_provider(), current_user)


@router.patch("/cards/{card_id}/status", response_model=BoardCardResponse)
def update_card_status(
    card_id: int,
    payload: CardStatusUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> BoardCardResponse:
    card = db.get(BoardCard, card_id)
    if card is None:
        raise HTTPException(status_code=404)
    board = card.board_list.board
    client = db.get(Client, board.client_id)
    if client is None:
        raise HTTPException(status_code=404)
    if current_user.role.code == "CLIENT" and current_user.client_id != client.id:
        raise HTTPException(status_code=403)
    board_service = BoardService(db)
    card = board_service.update_card_status(card=card, status=payload.status, actor=current_user, client=client)
    return BoardCardResponse(
        id=card.id,
        title=card.title,
        description_md=card.description_md,
        instructions_md=card.instructions_md,
        external_links=card.external_links,
        status=card.status,
        position=card.position,
        requires_credentials=card.requires_credentials,
        requires_file_upload=card.requires_file_upload,
        client_result_text=card.client_result_text,
    )


@router.post("/cards/{card_id}/comments", response_model=CardCommentResponse)
def add_comment(
    card_id: int,
    payload: CardCommentCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> CardCommentResponse:
    card = db.get(BoardCard, card_id)
    if card is None:
        raise HTTPException(status_code=404)
    client = db.get(Client, card.board_list.board.client_id)
    if current_user.role.code == "CLIENT":
        if current_user.client_id != client.id:
            raise HTTPException(status_code=403)
        payload.is_internal = False
    comment = BoardService(db).add_comment(
        card=card, author=current_user, body=payload.body, is_internal=payload.is_internal, client=client
    )
    return CardCommentResponse(
        id=comment.id,
        body=comment.body,
        is_internal=comment.is_internal,
        author_name=current_user.full_name,
        created_at=comment.created_at,
    )


@router.post("/cards/{card_id}/credentials", response_model=MessageResponse)
def submit_credentials(
    card_id: int,
    payload: CredentialSubmit,
    db: DbSession,
    current_user: CurrentUser,
) -> MessageResponse:
    if current_user.role.code != "CLIENT":
        raise HTTPException(status_code=403, detail="Solo el cliente puede entregar credenciales")
    card = db.get(BoardCard, card_id)
    if card is None or not card.requires_credentials:
        raise HTTPException(status_code=400)
    client = db.get(Client, current_user.client_id)
    if client is None:
        raise HTTPException(status_code=404)
    submission = CredentialSubmission(
        card_id=card.id,
        client_id=client.id,
        username_encrypted=encrypt_value(payload.username),
        password_encrypted=encrypt_value(payload.password),
    )
    db.add(submission)
    AuditService(db).log(
        actor=current_user,
        action="CREDENTIALS_SUBMITTED",
        entity_type="board_card",
        entity_id=card.id,
    )
    db.commit()
    return MessageResponse(message="Credenciales guardadas de forma segura")


@router.get("/cards/{card_id}/credentials")
def read_credentials(
    card_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("credentials:read"))],
) -> dict:
    from app.core.encryption import decrypt_value

    card = db.get(BoardCard, card_id)
    if card is None:
        raise HTTPException(status_code=404)
    sub = (
        db.execute(select(CredentialSubmission).where(CredentialSubmission.card_id == card_id))
        .scalars()
        .first()
    )
    if sub is None:
        raise HTTPException(status_code=404, detail="Sin credenciales")
    AuditService(db).log(
        actor=current_user,
        action="CREDENTIALS_VIEWED",
        entity_type="board_card",
        entity_id=card.id,
    )
    db.commit()
    return {
        "username": decrypt_value(sub.username_encrypted),
        "password": decrypt_value(sub.password_encrypted),
        "submitted_at": sub.submitted_at,
    }


@router.patch("/cards/{card_id}/result", response_model=MessageResponse)
def update_card_result(
    card_id: int,
    payload: CardResultUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> MessageResponse:
    card = db.get(BoardCard, card_id)
    if card is None:
        raise HTTPException(status_code=404)
    card.client_result_text = payload.client_result_text
    db.commit()
    return MessageResponse(message="Resultado actualizado")
