from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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


def _document_response(service: DocumentService, doc: Document) -> DocumentResponse:
    return service.to_response(doc)


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


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    document_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    db: DbSession,
    current_user: CurrentUser,
    client_id: int | None = None,
) -> DocumentResponse:
    if current_user.role.code != "CLIENT" and not client_id:
        raise HTTPException(status_code=400, detail="client_id requerido")
    client = _get_client_for_docs(current_user, client_id, db)
    service = DocumentService(db)
    file_bytes = await file.read()
    doc = service.upload_file(
        client=client,
        document_type=document_type,
        filename=file.filename or "document",
        content_type=file.content_type or "",
        file_bytes=file_bytes,
    )
    return _document_response(service, doc)


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
    return _document_response(service, doc)


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
    return [doc_service.to_response(d) for d in docs]
