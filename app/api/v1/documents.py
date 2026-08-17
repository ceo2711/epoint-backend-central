from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, OptionalActiveMerchantId, require_permissions
from app.models.client import Client
from app.models.document import Document
from app.models.user import User
from app.schemas.client import DocumentBrief
from app.schemas.document import ConfirmUploadRequest, DocumentResponse, UploadUrlRequest, UploadUrlResponse
from app.services.clients import ClientService
from app.services.documents import DocumentService
from app.services.storage import get_storage_provider

router = APIRouter(prefix="/documents", tags=["Documentos"])


def _require_can_upload_client_documents(user: User) -> None:
    from app.services.role_access import can_upload_client_documents

    if not can_upload_client_documents(user):
        raise HTTPException(
            status_code=403,
            detail="No autorizado a modificar documentos del cliente",
        )


def _get_client_for_docs(
    user: User,
    client_id: int | None,
    db,
    *,
    merchant_id: int | None = None,
) -> Client:
    if user.role.code == "CLIENT":
        if not user.client_id:
            raise HTTPException(status_code=403, detail="Sin cliente asociado")
        client = db.get(Client, user.client_id)
    elif client_id:
        service = ClientService(db)
        if not service.user_can_view_approved_client_workspace(user, client_id):
            raise HTTPException(status_code=403, detail="No autorizado")
        client = service.get_client_for_user(user, client_id, merchant_id=merchant_id)
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
    merchant_id: OptionalActiveMerchantId,
    client_id: int | None = None,
) -> UploadUrlResponse:
    if current_user.role.code != "CLIENT" and not client_id:
        raise HTTPException(status_code=400, detail="client_id requerido")
    _require_can_upload_client_documents(current_user)
    client = _get_client_for_docs(current_user, client_id, db, merchant_id=merchant_id)
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
    merchant_id: OptionalActiveMerchantId,
    client_id: int | None = None,
) -> DocumentResponse:
    if current_user.role.code != "CLIENT" and not client_id:
        raise HTTPException(status_code=400, detail="client_id requerido")
    _require_can_upload_client_documents(current_user)
    client = _get_client_for_docs(current_user, client_id, db, merchant_id=merchant_id)
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
    merchant_id: OptionalActiveMerchantId,
    client_id: int | None = None,
) -> DocumentResponse:
    _require_can_upload_client_documents(current_user)
    client = _get_client_for_docs(current_user, client_id, db, merchant_id=merchant_id)
    service = DocumentService(db)
    doc = service.confirm_upload(
        client=client,
        document_type=payload.document_type,
        storage_key=payload.storage_key,
        original_filename=payload.original_filename,
        mime_type=payload.mime_type,
    )
    return _document_response(service, doc)


def _get_document_for_user(db, user: User, document_id: int, *, merchant_id: int | None = None) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    if user.role.code == "CLIENT":
        if user.client_id != doc.client_id:
            raise HTTPException(status_code=403, detail="Sin acceso al documento")
    else:
        service = ClientService(db)
        if service.get_client_for_user(user, doc.client_id, merchant_id=merchant_id) is None:
            raise HTTPException(status_code=404, detail="Documento no encontrado")
    return doc


@router.get("/{document_id}/content")
def get_document_content(
    document_id: int,
    db: DbSession,
    current_user: CurrentUser,
    merchant_id: OptionalActiveMerchantId,
    download: bool = Query(False),
) -> StreamingResponse:
    doc = _get_document_for_user(db, current_user, document_id, merchant_id=merchant_id)
    if download:
        from app.services.role_access import can_download_client_documents

        if not can_download_client_documents(current_user):
            raise HTTPException(
                status_code=403,
                detail="No autorizado a descargar documentos del cliente",
            )
    storage = get_storage_provider()
    file_bytes, media_type = storage.get_object_bytes(doc.storage_key)
    disposition = "attachment" if download else "inline"
    return StreamingResponse(
        iter([file_bytes]),
        media_type=doc.mime_type or media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{doc.original_filename}"'},
    )


@router.get("/client/{client_id}", response_model=list[DocumentBrief])
def list_client_documents(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("documents:read"))],
    merchant_id: OptionalActiveMerchantId,
) -> list[DocumentBrief]:
    service_client = ClientService(db)
    client = service_client.get_client_for_user(current_user, client_id, merchant_id=merchant_id)
    if client is None:
        raise HTTPException(status_code=404)
    docs = db.execute(select(Document).where(Document.client_id == client_id)).scalars().all()
    doc_service = DocumentService(db)
    latest = doc_service.load_latest_verifications_map([d.id for d in docs])
    return [
        doc_service.to_brief(
            d,
            include_download_url=True,
            latest_verification=latest.get(d.id),
        )
        for d in docs
    ]
