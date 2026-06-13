import uuid
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.document import Document
from app.models.enums import ClientStatus, DocumentVerificationStatus, NotificationEventType
from app.models.user import User
from app.services.clients import ClientService
from app.services.notifications import NotificationService
from app.services.storage import get_storage_provider


REQUIRED_DOCUMENT_TYPES = [
    "SSN_CARD",
    "DRIVERS_LICENSE_FRONT",
    "DRIVERS_LICENSE_BACK",
    "UTILITY_BILL",
]

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}

MIME_BY_EXTENSION = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


class DocumentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.storage = get_storage_provider()
        self.notifications = NotificationService(db)

    def resolve_content_type(self, content_type: str, filename: str) -> str:
        normalized = content_type.split(";")[0].strip().lower()
        if normalized in ALLOWED_MIME_TYPES:
            return "image/jpeg" if normalized == "image/jpg" else normalized
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return MIME_BY_EXTENSION.get(ext, normalized)

    def build_storage_key(self, *, client: Client, document_type: str, filename: str) -> str:
        ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
        return self.storage.build_key(
            "clients", str(client.id), "documents", document_type, f"{uuid.uuid4()}.{ext}"
        )

    def request_upload_url(
        self,
        *,
        client: Client,
        document_type: str,
        filename: str,
        content_type: str,
    ) -> dict:
        mime_type = self.resolve_content_type(content_type, filename)
        if mime_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=400, detail="Tipo de archivo no permitido")
        key = self.build_storage_key(client=client, document_type=document_type, filename=filename)
        upload_url = self.storage.generate_upload_url(key, mime_type)
        return {"upload_url": upload_url, "storage_key": key, "content_type": mime_type}

    def upload_file(
        self,
        *,
        client: Client,
        document_type: str,
        filename: str,
        content_type: str,
        file_bytes: bytes,
    ) -> Document:
        if not file_bytes:
            raise HTTPException(status_code=400, detail="El archivo está vacío")
        mime_type = self.resolve_content_type(content_type, filename)
        if mime_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=400, detail="Tipo de archivo no permitido")
        key = self.build_storage_key(client=client, document_type=document_type, filename=filename)
        self.storage.put_object(key, file_bytes, mime_type)
        return self.confirm_upload(
            client=client,
            document_type=document_type,
            storage_key=key,
            original_filename=filename,
            mime_type=mime_type,
        )

    def confirm_upload(
        self,
        *,
        client: Client,
        document_type: str,
        storage_key: str,
        original_filename: str,
        mime_type: str,
    ) -> Document:
        if not self.storage.object_exists(storage_key):
            raise HTTPException(status_code=400, detail="El archivo no fue subido correctamente")

        existing = self.db.execute(
            select(Document).where(Document.client_id == client.id, Document.type == document_type)
        ).scalar_one_or_none()
        if existing:
            self.storage.delete_object(existing.storage_key)
            existing.storage_key = storage_key
            existing.original_filename = original_filename
            existing.mime_type = mime_type
            existing.verification_status = DocumentVerificationStatus.PENDIENTE.value
            doc = existing
        else:
            doc = Document(
                client_id=client.id,
                type=document_type,
                storage_key=storage_key,
                original_filename=original_filename,
                mime_type=mime_type,
                verification_status=DocumentVerificationStatus.PENDIENTE.value,
            )
            self.db.add(doc)

        if client.status == ClientStatus.EN_CARGA_DATOS.value:
            client_service = ClientService(self.db)
            if client_service.check_data_complete(client):
                client.status = ClientStatus.DOCUMENTOS_EN_REVISION.value
                client_service.on_documents_complete(client=client)

        doc.verification_status = DocumentVerificationStatus.EN_PROCESO.value
        self.db.commit()
        self.db.refresh(doc)

        from app.workers.enqueue import enqueue_document_verification

        enqueue_document_verification(doc.id)

        return doc

    def get_download_url(self, document: Document) -> str:
        return self.storage.generate_download_url(document.storage_key)

    def to_brief(self, document: Document, *, include_download_url: bool = True) -> "DocumentBrief":
        from app.schemas.client import DocumentBrief

        return DocumentBrief(
            id=document.id,
            type=document.type,
            verification_status=document.verification_status,
            original_filename=document.original_filename,
            expires_at=document.expires_at,
            uploaded_at=document.uploaded_at,
            mime_type=document.mime_type,
            download_url=self.get_download_url(document) if include_download_url else None,
        )

    def to_response(self, document: Document) -> "DocumentResponse":
        from app.schemas.document import DocumentResponse

        return DocumentResponse(
            id=document.id,
            type=document.type,
            verification_status=document.verification_status,
            original_filename=document.original_filename,
            mime_type=document.mime_type,
            download_url=self.get_download_url(document),
        )

    def mark_expiring_soon(self, document: Document, client: Client) -> None:
        document.verification_status = DocumentVerificationStatus.PROXIMO_A_VENCER.value
        portal_users = list(
            self.db.execute(select(User).where(User.client_id == client.id)).scalars().all()
        )
        self.notifications.notify(
            event_type=NotificationEventType.DOCUMENT_EXPIRING_SOON.value,
            users=portal_users,
            title="Documento próximo a vencer",
            body=f"Tu documento {document.type} vence pronto. Subí una versión actualizada.",
            payload={"document_id": document.id, "client_id": client.id},
        )
        self.db.commit()

    def all_documents_approved(self, client_id: int) -> bool:
        docs = self.db.execute(select(Document).where(Document.client_id == client_id)).scalars().all()
        if len(docs) < len(REQUIRED_DOCUMENT_TYPES):
            return False
        return all(d.verification_status == DocumentVerificationStatus.APROBADO.value for d in docs)
