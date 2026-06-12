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


class DocumentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.storage = get_storage_provider()
        self.notifications = NotificationService(db)

    def request_upload_url(
        self,
        *,
        client: Client,
        document_type: str,
        filename: str,
        content_type: str,
    ) -> dict:
        if content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=400, detail="Tipo de archivo no permitido")
        ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
        key = self.storage.build_key(
            "clients", str(client.id), "documents", document_type, f"{uuid.uuid4()}.{ext}"
        )
        upload_url = self.storage.generate_upload_url(key, content_type)
        return {"upload_url": upload_url, "storage_key": key, "content_type": content_type}

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

        self.db.flush()

        from app.workers.tasks import verify_document_task

        try:
            verify_document_task.delay(doc.id)
        except Exception:
            verify_document_task(doc.id)

        if client.status == ClientStatus.EN_CARGA_DATOS.value:
            client_service = ClientService(self.db)
            if client_service.check_data_complete(client):
                client.status = ClientStatus.DOCUMENTOS_EN_REVISION.value
                client_service.on_documents_complete(client=client)

        self.db.commit()
        self.db.refresh(doc)
        return doc

    def get_download_url(self, document: Document) -> str:
        return self.storage.generate_download_url(document.storage_key)

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
