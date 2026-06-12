import json
import logging
from datetime import date, timedelta

from app.core.database import SessionLocal
from app.models.client import Client
from app.models.document import Document
from app.models.document_verification import DocumentVerification
from app.models.enums import DocumentVerificationStatus, NotificationEventType
from app.models.role import Role
from app.models.user import User
from app.services.clients import ClientService
from app.services.llm import get_llm_service
from app.services.notifications import NotificationService
from app.services.storage import get_storage_provider
from app.workers.celery_app import celery_app
from sqlalchemy import select

logger = logging.getLogger(__name__)

VERIFICATION_PROMPT = """Analizá este documento de identidad o comprobante y respondé ÚNICAMENTE con JSON válido:
{
  "is_readable": true/false,
  "is_complete": true/false,
  "is_color": true/false,
  "corners_cut": true/false,
  "is_expired": true/false,
  "expires_at": "YYYY-MM-DD o null",
  "name_matches": true/false,
  "address_matches": true/false,
  "rejection_reasons": ["motivo1", ...]
}
Criterios: legible, completo, a color, sin esquinas cortadas, vigente.
Para utility bill/bank statement verificar nombre y dirección si se proporcionan datos del cliente."""


@celery_app.task(name="verify_document")
def verify_document_task(document_id: int) -> dict:
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is None:
            return {"error": "document not found"}

        client = db.get(Client, document.client_id)
        if client is None:
            return {"error": "client not found"}

        document.verification_status = DocumentVerificationStatus.EN_PROCESO.value
        db.commit()

        storage = get_storage_provider()
        download_url = storage.generate_download_url(document.storage_key, expires_in=600)

        llm = get_llm_service()
        client_context = (
            f"Cliente: {client.first_name} {client.last_name}. "
            f"Tipo documento: {document.type}."
        )
        try:
            result_text = llm.analyze_document_sync(
                image_url=download_url,
                prompt=f"{VERIFICATION_PROMPT}\n{client_context}",
            )
            result = json.loads(result_text.strip().removeprefix("```json").removesuffix("```").strip())
        except Exception as exc:
            logger.exception("Error verificando documento %s", document_id)
            result = {
                "is_readable": False,
                "rejection_reasons": [f"Error de verificación IA: {str(exc)}"],
            }

        rejection_reasons = result.get("rejection_reasons", [])
        approved = (
            result.get("is_readable", False)
            and result.get("is_complete", False)
            and result.get("is_color", False)
            and not result.get("corners_cut", True)
            and not result.get("is_expired", True)
        )

        if document.type in ("UTILITY_BILL", "BANK_STATEMENT"):
            approved = approved and result.get("name_matches", False) and result.get("address_matches", False)

        status = DocumentVerificationStatus.APROBADO.value if approved else DocumentVerificationStatus.RECHAZADO.value
        document.verification_status = status

        expires_str = result.get("expires_at")
        if expires_str:
            try:
                document.expires_at = date.fromisoformat(expires_str)
                if document.expires_at <= date.today() + timedelta(days=30):
                    document.verification_status = DocumentVerificationStatus.PROXIMO_A_VENCER.value
            except ValueError:
                pass

        verification = DocumentVerification(
            document_id=document.id,
            status=document.verification_status,
            ai_model=llm.model_name if llm.is_available else "unavailable",
            raw_response=result,
            rejection_reasons=rejection_reasons if rejection_reasons else None,
        )
        db.add(verification)

        notifications = NotificationService(db)
        portal_users = list(db.execute(select(User).where(User.client_id == client.id)).scalars().all())

        if not approved:
            if portal_users:
                notifications.notify(
                    event_type=NotificationEventType.DOCUMENT_REJECTED.value,
                    users=portal_users,
                    title="Documento rechazado",
                    body=f"Tu documento {document.type} no pasó la verificación: {', '.join(rejection_reasons) or 'revisar calidad'}",
                    payload={"document_id": document.id},
                )
            onboarding = list(
                db.execute(
                    select(User).join(Role).where(Role.code.in_(["ONBOARDING_MANAGER", "ADMIN"]))
                ).scalars().all()
            )
            notifications.notify(
                event_type=NotificationEventType.DOCUMENT_REJECTED.value,
                users=onboarding,
                title="Documento rechazado por IA",
                body=f"Documento de {client.full_name} rechazado: {document.type}",
                payload={"document_id": document.id, "client_id": client.id},
            )
        elif document.verification_status == DocumentVerificationStatus.PROXIMO_A_VENCER.value and portal_users:
            notifications.notify(
                event_type=NotificationEventType.DOCUMENT_EXPIRING_SOON.value,
                users=portal_users,
                title="Documento próximo a vencer",
                body=f"Tu {document.type} vence el {document.expires_at}",
                payload={"document_id": document.id},
            )

        db.commit()

        client_service = ClientService(db)
        if client_service.check_data_complete(client):
            from app.services.documents import DocumentService

            doc_service = DocumentService(db)
            if doc_service.all_documents_approved(client.id):
                client.status = "LISTO_PARA_TABLERO"
                db.commit()
                client_service.try_create_board(client=client)

        return {"document_id": document_id, "status": document.verification_status}
    finally:
        db.close()


@celery_app.task(name="send_notification_async")
def send_notification_async(notification_id: int) -> None:
    # Reservado para reintentos de email/WhatsApp en Fase 6
    logger.info("send_notification_async %s", notification_id)
