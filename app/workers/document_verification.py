"""Verificación IA de documentos — único lugar donde se invoca Gemini/LangChain."""

import json
import logging
from datetime import date, timedelta

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.client import Client
from app.models.document import Document
from app.models.document_verification import DocumentVerification
from app.models.enums import DocumentVerificationStatus, NotificationEventType
from app.models.role import Role
from app.models.user import User
from app.services.notifications import NotificationService
from app.services.storage import get_storage_provider

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


def run_document_verification(document_id: int) -> dict:
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is None:
            logger.error("Documento %s no encontrado para verificación", document_id)
            return {"error": "document not found"}

        client = db.get(Client, document.client_id)
        if client is None:
            logger.error("Cliente no encontrado para documento %s", document_id)
            return {"error": "client not found"}

        if document.verification_status == DocumentVerificationStatus.PENDIENTE.value:
            document.verification_status = DocumentVerificationStatus.EN_PROCESO.value
            db.commit()

        storage = get_storage_provider()
        file_bytes, media_type = storage.get_object_bytes(document.storage_key)

        from app.services.llm import get_llm_service

        llm = get_llm_service()
        client_context = (
            f"Cliente: {client.first_name} {client.last_name}. "
            f"Tipo documento: {document.type}."
        )
        try:
            result_text = llm.analyze_document_bytes(
                content=file_bytes,
                media_type=document.mime_type or media_type,
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
                    payload={"document_id": document.id, "client_id": client.id},
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
                payload={"document_id": document.id, "client_id": client.id},
            )

        db.commit()

        return {"document_id": document_id, "status": document.verification_status}
    except Exception:
        logger.exception("Fallo crítico verificando documento %s", document_id)
        try:
            document = db.get(Document, document_id)
            if document:
                document.verification_status = DocumentVerificationStatus.RECHAZADO.value
                db.commit()
        except Exception:
            logger.exception("No se pudo marcar documento %s como rechazado", document_id)
        raise
    finally:
        db.close()
