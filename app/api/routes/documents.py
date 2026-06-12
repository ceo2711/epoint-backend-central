from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_permissions
from app.models.client import Client
from app.models.document import Document
from app.models.user import User
from app.schemas.document import ConfirmUploadRequest, DocumentResponse, UploadUrlRequest, UploadUrlResponse
from app.services.clients import ClientService
from app.services.documents import DocumentService

router = APIRouter(prefix="/documents", tags=["Documentos"])


def _get_client_for_docs(user: User, client_id: int | None, db) -> Client:
    if user.role.code == "CLIENT":
        if not user.client_id:
            raise HTTPException(status_code=403, detail="Sin cliente asociado")
        client = db.get(Client, user.client_id)
    elif client_id:
        service = ClientService(db)
        client = service.get_client_for_user(user, client_id)
    else:
        raise HTTPException(status_code=400, detail="client_id requerido")
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return client


@router.post("/upload-url", response_model=UploadUrlResponse)
def request_upload_url(
    payload: UploadUrlRequest,
    db: DbSession,
    current_user: CurrentUser,
    client_id: int | None = None,
) -> UploadUrlResponse:
    if current_user.role.code != "CLIENT" and not client_id:
        raise HTTPException(status_code=400, detail="client_id requerido")
    client = _get_client_for_docs(current_user, client_id, db)
    service = DocumentService(db)
    result = service.request_upload_url(
        client=client,
        document_type=payload.document_type,
        filename=payload.filename,
        content_type=payload.content_type,
    )
    return UploadUrlResponse(**result)


@router.post("/confirm", response_model=DocumentResponse)
def confirm_upload(
    payload: ConfirmUploadRequest,
    db: DbSession,
    current_user: CurrentUser,
    client_id: int | None = None,
) -> DocumentResponse:
    client = _get_client_for_docs(current_user, client_id, db)
    service = DocumentService(db)
    doc = service.confirm_upload(
        client=client,
        document_type=payload.document_type,
        storage_key=payload.storage_key,
        original_filename=payload.original_filename,
        mime_type=payload.mime_type,
    )
    return DocumentResponse(
        id=doc.id,
        type=doc.type,
        verification_status=doc.verification_status,
        original_filename=doc.original_filename,
    )


@router.get("/client/{client_id}", response_model=list[DocumentResponse])
def list_client_documents(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("documents:read"))],
) -> list[DocumentResponse]:
    service_client = ClientService(db)
    client = service_client.get_client_for_user(current_user, client_id)
    if client is None:
        raise HTTPException(status_code=404)
    docs = db.execute(select(Document).where(Document.client_id == client_id)).scalars().all()
    doc_service = DocumentService(db)
    return [
        DocumentResponse(
            id=d.id,
            type=d.type,
            verification_status=d.verification_status,
            original_filename=d.original_filename,
            download_url=doc_service.get_download_url(d),
        )
        for d in docs
    ]
