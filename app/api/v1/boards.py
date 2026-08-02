from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, OptionalActiveMerchantId, require_permissions
from app.core.encryption import encrypt_value
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.card_attachment import CardAttachment
from app.models.card_attachment_verification import CardAttachmentVerification
from app.models.client import Client
from app.models.credential_submission import CredentialSubmission
from app.models.document import Document
from app.models.user import User
from app.schemas.board import (
    BoardCardResponse,
    BoardListResponse,
    BoardMentionableUserResponse,
    BoardResponse,
    CardAttachmentResponse,
    CardCommentResponse,
    CardCreate,
    CardLabelUpdate,
    CardMoveUpdate,
    CardResultUpdate,
    CardStatusUpdate,
    CardUpdate,
    CredentialSubmit,
)
from app.schemas.common import MessageResponse
from app.services.audit import AuditService
from app.services.boards import BoardService
from app.services.clients import ClientService
from app.services.storage import get_storage_provider

router = APIRouter(prefix="/boards", tags=["Tableros"])


def _require_staff_client_workspace(
    db: DbSession,
    user: User,
    client_id: int,
    merchant_id: int | None,
) -> Client:
    cs = ClientService(db)
    client = cs.get_client_for_user(user, client_id, merchant_id=merchant_id)
    if client is None or not cs.user_can_view_approved_client_workspace(user, client_id, client=client):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return client

BOARD_STAFF_ROLES = frozenset(
    {"ADMIN", "BRANCH_MANAGER", "ADVISOR", "AREA_LEADER"}
)


def _is_board_staff(user: User) -> bool:
    return user.role.code in BOARD_STAFF_ROLES


def _require_board_staff(user: User) -> None:
    if not _is_board_staff(user):
        raise HTTPException(status_code=403, detail="No tenés permiso para modificar el tablero")


def _require_board_card_delete(user: User) -> None:
    from app.services.role_access import is_onboarding_area_leader

    if user.role.code == "ADVISOR" or is_onboarding_area_leader(user):
        return
    raise HTTPException(
        status_code=403,
        detail="Solo asesores y líderes de onboarding pueden eliminar cards",
    )


def _require_card_label_editor(user: User, client: Client, db) -> None:
    """Solo onboarding o un asesor asignado del cliente pueden setear labels."""
    from app.services.role_access import is_onboarding_area_leader

    if is_onboarding_area_leader(user):
        return
    if user.role.code == "ADVISOR":
        advisors = ClientService(db)._get_active_advisors(client)
        if any(advisor.id == user.id for advisor in advisors):
            return
    raise HTTPException(
        status_code=403,
        detail="Solo onboarding o un asesor asignado pueden cambiar el label de la card",
    )


def _lite_card_response(card: BoardCard) -> BoardCardResponse:
    return BoardCardResponse(
        id=card.id,
        title=card.title,
        description_md=card.description_md,
        instructions_md=card.instructions_md,
        external_links=card.external_links,
        status=card.status,
        label=card.label,
        position=card.position,
        requires_credentials=card.requires_credentials,
        requires_file_upload=card.requires_file_upload,
        client_result_text=card.client_result_text,
    )


def _attachment_response(
    attachment: CardAttachment,
    storage,
    board_service: BoardService,
    *,
    include_download_url: bool = False,
    latest_verification: CardAttachmentVerification | None = None,
) -> CardAttachmentResponse:
    download_url = storage.generate_download_url(attachment.storage_key) if include_download_url else None
    rejection_reasons, approval_reasons = board_service.latest_attachment_verification_messages(
        attachment,
        latest_verification=latest_verification,
    )
    return CardAttachmentResponse(
        id=attachment.id,
        type=attachment.type,
        original_filename=attachment.original_filename,
        mime_type=attachment.mime_type,
        download_url=download_url,
        comment_id=attachment.comment_id,
        uploaded_by_name=attachment.uploaded_by.full_name if attachment.uploaded_by else None,
        created_at=attachment.created_at,
        verification_status=attachment.verification_status,
        rejection_reasons=rejection_reasons,
        approval_reasons=approval_reasons,
    )


def _card_response(
    card: BoardCard,
    storage,
    board_service: BoardService,
    *,
    verifications_map: dict[int, CardAttachmentVerification] | None = None,
) -> BoardCardResponse:
    verifications_map = verifications_map or {}
    comments = [
        CardCommentResponse(
            id=c.id,
            body=c.body,
            is_internal=c.is_internal,
            author_name=c.author.full_name if c.author else "—",
            created_at=c.created_at,
        )
        for c in card.comments
    ]
    attachments = [
        _attachment_response(
            a,
            storage,
            board_service,
            latest_verification=verifications_map.get(a.id),
        )
        for a in card.attachments
    ]
    return BoardCardResponse(
        id=card.id,
        title=card.title,
        description_md=card.description_md,
        instructions_md=card.instructions_md,
        external_links=card.external_links,
        status=card.status,
        label=card.label,
        position=card.position,
        requires_credentials=card.requires_credentials,
        requires_file_upload=card.requires_file_upload,
        client_result_text=card.client_result_text,
        comments=comments,
        attachments=attachments,
        has_credentials=len(card.credential_submissions) > 0,
    )


def _get_card_client(
    card: BoardCard,
    current_user: User,
    db,
    *,
    merchant_id: int | None = None,
) -> Client:
    client = db.get(Client, card.board_list.board.client_id)
    if client is None:
        raise HTTPException(status_code=404)
    if current_user.role.code == "CLIENT" and current_user.client_id != client.id:
        raise HTTPException(status_code=403)
    if current_user.role.code != "CLIENT":
        return _require_staff_client_workspace(db, current_user, client.id, merchant_id)
    return client


def _get_attachment_for_user(
    attachment_id: int,
    current_user: User,
    db,
    *,
    merchant_id: int | None = None,
) -> CardAttachment:
    attachment = db.get(CardAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")
    _get_card_client(attachment.card, current_user, db, merchant_id=merchant_id)
    return attachment


def _build_board_response(board, storage, user: User, board_service: BoardService) -> BoardResponse:
    all_attachment_ids = [
        attachment.id
        for bl in board.lists
        for card in bl.cards
        for attachment in card.attachments
    ]
    verifications_map = board_service.load_latest_attachment_verifications_map(all_attachment_ids)

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
                _attachment_response(
                    a,
                    storage,
                    board_service,
                    latest_verification=verifications_map.get(a.id),
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
                    label=card.label,
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
    merchant_id: OptionalActiveMerchantId,
) -> BoardResponse:
    if current_user.role.code == "CLIENT" and current_user.client_id != client_id:
        raise HTTPException(status_code=403)
    if current_user.role.code != "CLIENT":
        _require_staff_client_workspace(db, current_user, client_id, merchant_id)

    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    from app.services.client_onboarding_status import client_has_board_access, is_board_unlocked

    # El cliente solo ve el tablero cuando datos + docs mínimos están OK.
    if current_user.role.code == "CLIENT":
        docs = list(
            db.execute(select(Document).where(Document.client_id == client_id)).scalars().all()
        )
        if not client_has_board_access(client, docs):
            raise HTTPException(
                status_code=404,
                detail="El tablero se habilita cuando completes tus datos y documentos",
            )

    board_service = BoardService(db)
    board = board_service.get_board_for_client(client_id)
    if board is None:
        # Crear si el cliente ya está listo, o si staff necesita previsualizar post-aprobación.
        can_create = is_board_unlocked(client.status) or (
            current_user.role.code != "CLIENT" and bool(client.approved_at)
        )
        if can_create:
            board_service.create_from_template(client)
            db.commit()
            board = board_service.get_board_for_client(client_id)
    if board is None:
        raise HTTPException(status_code=404, detail="Tablero no encontrado")
    return _build_board_response(board, get_storage_provider(), current_user, board_service)


@router.get("/client/{client_id}/mentionable-users", response_model=list[BoardMentionableUserResponse])
def list_mentionable_users(
    client_id: int,
    db: DbSession,
    current_user: CurrentUser,
    merchant_id: OptionalActiveMerchantId,
    include_client: bool = True,
) -> list[BoardMentionableUserResponse]:
    if current_user.role.code == "CLIENT" and current_user.client_id != client_id:
        raise HTTPException(status_code=403)
    cs = ClientService(db)
    if current_user.role.code != "CLIENT":
        # Valida acceso y luego carga relaciones (asesores) para el autocomplete
        _require_staff_client_workspace(db, current_user, client_id, merchant_id)
        client = cs.get_client_detail(client_id)
    else:
        client = cs.get_client_detail(client_id)
    if client is None:
        raise HTTPException(status_code=404)

    users = cs.get_mentionable_users(
        client=client,
        current_user=current_user,
        include_client=include_client,
    )
    return [
        BoardMentionableUserResponse(
            id=user.id,
            full_name=user.full_name,
            role_code=user.role.code,
        )
        for user in users
    ]


@router.post("/lists/{list_id}/cards", response_model=BoardCardResponse)
def create_card(
    list_id: int,
    payload: CardCreate,
    db: DbSession,
    current_user: CurrentUser,
    merchant_id: OptionalActiveMerchantId,
) -> BoardCardResponse:
    board_list = db.get(BoardList, list_id)
    if board_list is None:
        raise HTTPException(status_code=404, detail="Columna no encontrada")

    board = board_list.board
    client = db.get(Client, board.client_id)
    if client is None:
        raise HTTPException(status_code=404)
    if current_user.role.code == "CLIENT" and current_user.client_id != client.id:
        raise HTTPException(status_code=403)
    if current_user.role.code != "CLIENT":
        _require_staff_client_workspace(db, current_user, client.id, merchant_id)
        _require_board_staff(current_user)

    board_service = BoardService(db)
    try:
        card = board_service.create_card(
            board_list=board_list,
            title=payload.title,
            position=payload.position,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _lite_card_response(card)


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
    return _lite_card_response(card)


@router.patch("/cards/{card_id}/move", response_model=BoardCardResponse)
def move_card(
    card_id: int,
    payload: CardMoveUpdate,
    db: DbSession,
    current_user: CurrentUser,
    merchant_id: OptionalActiveMerchantId,
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
    if current_user.role.code != "CLIENT":
        _require_staff_client_workspace(db, current_user, client.id, merchant_id)
    _require_board_staff(current_user)

    board_service = BoardService(db)
    try:
        card = board_service.move_card(
            card=card,
            target_list_id=payload.list_id,
            target_position=payload.position,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _lite_card_response(card)


@router.patch("/cards/{card_id}", response_model=BoardCardResponse)
def update_card(
    card_id: int,
    payload: CardUpdate,
    db: DbSession,
    current_user: CurrentUser,
    merchant_id: OptionalActiveMerchantId,
) -> BoardCardResponse:
    card = db.get(BoardCard, card_id)
    if card is None:
        raise HTTPException(status_code=404)
    _get_card_client(card, current_user, db, merchant_id=merchant_id)
    _require_board_staff(current_user)

    board_service = BoardService(db)
    try:
        card = board_service.update_card(
            card=card,
            title=payload.title,
            description_md=payload.description_md,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _lite_card_response(card)


@router.patch("/cards/{card_id}/label", response_model=BoardCardResponse)
def update_card_label(
    card_id: int,
    payload: CardLabelUpdate,
    db: DbSession,
    current_user: CurrentUser,
    merchant_id: OptionalActiveMerchantId,
) -> BoardCardResponse:
    card = db.get(BoardCard, card_id)
    if card is None:
        raise HTTPException(status_code=404)
    client = _get_card_client(card, current_user, db, merchant_id=merchant_id)
    _require_card_label_editor(current_user, client, db)

    label_value = payload.label.value if payload.label is not None else None
    card = BoardService(db).update_card_label(card=card, label=label_value)
    return _lite_card_response(card)


@router.delete("/cards/{card_id}", response_model=MessageResponse)
def delete_card(
    card_id: int,
    db: DbSession,
    current_user: CurrentUser,
    merchant_id: OptionalActiveMerchantId,
) -> MessageResponse:
    card = db.get(BoardCard, card_id)
    if card is None:
        raise HTTPException(status_code=404)
    _get_card_client(card, current_user, db, merchant_id=merchant_id)
    _require_board_card_delete(current_user)

    BoardService(db).delete_card(card=card)
    return MessageResponse(message="Card eliminada")


@router.post("/cards/{card_id}/attachments", response_model=CardAttachmentResponse)
async def upload_card_attachment(
    card_id: int,
    db: DbSession,
    current_user: CurrentUser,
    merchant_id: OptionalActiveMerchantId,
    file: Annotated[UploadFile, File()],
    comment_id: Annotated[int | None, Form()] = None,
    attachment_type: Annotated[str, Form()] = "CLIENT_UPLOAD",
) -> CardAttachmentResponse:
    card = db.get(BoardCard, card_id)
    if card is None:
        raise HTTPException(status_code=404)
    client = _get_card_client(card, current_user, db, merchant_id=merchant_id)

    file_bytes = await file.read()
    board_service = BoardService(db)
    try:
        attachment = board_service.upload_attachment(
            card=card,
            actor=current_user,
            client=client,
            filename=file.filename or "attachment",
            content_type=file.content_type or "",
            file_bytes=file_bytes,
            attachment_type=attachment_type,
            comment_id=comment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    storage = get_storage_provider()
    return _attachment_response(attachment, storage, board_service)


@router.get("/attachments/{attachment_id}/content")
def get_attachment_content(
    attachment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    merchant_id: OptionalActiveMerchantId,
) -> StreamingResponse:
    attachment = _get_attachment_for_user(attachment_id, current_user, db, merchant_id=merchant_id)
    storage = get_storage_provider()
    file_bytes, media_type = storage.get_object_bytes(attachment.storage_key)
    return StreamingResponse(
        iter([file_bytes]),
        media_type=attachment.mime_type or media_type,
        headers={"Content-Disposition": f'inline; filename="{attachment.original_filename}"'},
    )


@router.post("/cards/{card_id}/comments", response_model=CardCommentResponse)
async def add_comment(
    card_id: int,
    db: DbSession,
    current_user: CurrentUser,
    merchant_id: OptionalActiveMerchantId,
    body: Annotated[str, Form()] = "",
    is_internal: Annotated[bool, Form()] = False,
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> CardCommentResponse:
    card = db.get(BoardCard, card_id)
    if card is None:
        raise HTTPException(status_code=404)
    client = db.get(Client, card.board_list.board.client_id)
    if client is None:
        raise HTTPException(status_code=404)
    if current_user.role.code == "CLIENT":
        if current_user.client_id != client.id:
            raise HTTPException(status_code=403)
        is_internal = False
    else:
        _require_staff_client_workspace(db, current_user, client.id, merchant_id)

    attachments: list[tuple[str, str, bytes]] = []
    for upload in files or []:
        file_bytes = await upload.read()
        if not file_bytes:
            continue
        attachments.append(
            (
                upload.filename or "attachment",
                upload.content_type or "",
                file_bytes,
            )
        )

    if not body.strip() and not attachments:
        raise HTTPException(status_code=400, detail="El comentario o al menos un archivo es obligatorio")

    board_service = BoardService(db)
    try:
        comment = board_service.add_comment(
            card=card,
            author=current_user,
            body=body,
            is_internal=is_internal,
            client=client,
            attachments=attachments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
