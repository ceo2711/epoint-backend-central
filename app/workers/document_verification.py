"""Verificación IA de documentos — único lugar donde se invoca Gemini."""

import json
import logging
from datetime import date, timedelta

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.client import Client
from app.models.document import Document
from app.models.document_verification import DocumentVerification
from app.models.enums import DocumentVerificationStatus, NotificationEventType
from app.models.user import User
from app.services.document_requirements import document_needs_client_action
from app.services.document_verification_messages import (
    build_approval_messages,
    build_rejection_messages,
    system_verification_failure_result,
)
from app.services.document_verification_rules import (
    build_document_type_context,
    is_verification_approved,
    normalize_verification_result,
)
from app.services.notifications import NotificationService
from app.services.storage import get_storage_provider

logger = logging.getLogger(__name__)

VERIFICATION_PROMPT = """Analyze the uploaded file for onboarding verification and respond ONLY with valid JSON:
{
  "is_readable": true/false,
  "is_complete": true/false,
  "is_color": true/false,
  "corners_cut": true/false,
  "is_expired": true/false,
  "expires_at": "YYYY-MM-DD or null",
  "document_type_matches": true/false,
  "detected_document_type": "short label of what the file actually is (e.g. SSN card, invoice, bank statement)",
  "detected_name": "name printed on the document or null",
  "name_matches": true/false,
  "address_matches": true/false,
  "rejection_reasons": [{"en": "English reason", "es": "Motivo en español"}],
  "approval_reasons": [{"en": "English detail", "es": "Detalle en español"}]
}

Critical rules:
- Always respect Today's date from the context block when judging whether dates are past, current, or future.
- Prefer APPROVING imperfect but usable phone photos. Reject only for: wrong primary document type, unreadable blur, clearly different person, or clearly expired ID.
- Judge the DOMINANT / PRIMARY document in the frame. If another paper is partially visible underneath or in the background, IGNORE it.
- document_type_matches: true when the primary subject is the requested type (or a close accepted alternative for that slot). false only when the primary subject is clearly something else.
- detected_document_type must describe the primary document you see.
- is_complete: true unless large parts of the primary document are missing from the frame. Background clutter does not make it incomplete.
- is_color: true for normal camera photos/scans; do not reject for mild color cast or near-grayscale.
- corners_cut: true ONLY when a major corner of the primary document is cropped out of the photo.
- detected_name must be the name as printed on the document (or null if none).
- name_matches: Prefer true for the same person (abbreviations/OCR typos OK). false only for a clearly different person. For DRIVERS_LICENSE_BACK, set name_matches=true when the image is clearly the license back.
- address_matches: Prefer true when any service/mailing address is visible on utility bills / bank statements.
- is_expired: only for ID documents with a real expiration date visible (license FRONT, passport, green card, work permit). For SSN cards, utility bills, bank statements, and driver's license BACK always set is_expired=false and expires_at=null unless a clear past expiration is visible on that side.
- Every reason must include both "en" and "es".
- If rejected, rejection_reasons must explain the main issue.
- If approved, approval_reasons must cite verified facts — never claim a match that is false."""


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

        previous_status = document.verification_status

        if document.verification_status == DocumentVerificationStatus.PENDIENTE.value:
            document.verification_status = DocumentVerificationStatus.EN_PROCESO.value
            db.commit()

        storage = get_storage_provider()
        file_bytes, media_type = storage.get_object_bytes(document.storage_key)

        from app.services.llm import get_llm_service

        llm = get_llm_service()
        client_name = f"{client.first_name} {client.last_name}".strip()
        type_context = build_document_type_context(
            document.type,
            client_name,
            today=date.today(),
        )
        try:
            result_text = llm.analyze_document_bytes(
                content=file_bytes,
                media_type=document.mime_type or media_type,
                prompt=f"{VERIFICATION_PROMPT}\n\n{type_context}",
            )
            result = json.loads(result_text.strip().removeprefix("```json").removesuffix("```").strip())
        except Exception:
            logger.exception("Error verificando documento %s", document_id)
            result = system_verification_failure_result()

        result = normalize_verification_result(result, document.type, client_name=client_name)
        approved = is_verification_approved(result, document.type, client_name=client_name)

        expires_str = result.get("expires_at")
        rejection_messages: list[dict[str, str]] = []
        approval_messages: list[dict[str, str]] = []

        if approved:
            approval_messages = build_approval_messages(
                result,
                document_type=document.type,
                client_name=client_name,
                expires_at=expires_str if isinstance(expires_str, str) else None,
            )
            status = DocumentVerificationStatus.APROBADO.value
        else:
            rejection_messages = build_rejection_messages(
                result,
                document_type=document.type,
                client_name=client_name,
            )
            status = DocumentVerificationStatus.RECHAZADO.value

        document.verification_status = status

        if expires_str and approved:
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
            rejection_reasons=rejection_messages or None,
            approval_reasons=approval_messages or None,
        )
        db.add(verification)

        notifications = NotificationService(db)
        portal_users = list(db.execute(select(User).where(User.client_id == client.id)).scalars().all())

        client_documents = list(
            db.execute(select(Document).where(Document.client_id == client.id)).scalars().all()
        )
        # Una alternativa ya cubierta (licencia aprobada) deja de ser un pendiente:
        # no hay que avisar por la green card rechazada.
        needs_client_action = document_needs_client_action(client_documents, document.type)

        if not approved:
            rejection_es = [item["es"] for item in rejection_messages]
            if (
                portal_users
                and needs_client_action
                and previous_status != DocumentVerificationStatus.RECHAZADO.value
            ):
                notifications.notify(
                    event_type=NotificationEventType.DOCUMENT_REJECTED.value,
                    users=portal_users,
                    title="Documento rechazado",
                    body=f"Tu documento {document.type} no pasó la verificación: {', '.join(rejection_es) or 'revisar calidad'}",
                    payload={"document_id": document.id, "client_id": client.id},
                )
        elif (
            document.verification_status == DocumentVerificationStatus.PROXIMO_A_VENCER.value
            and portal_users
            and needs_client_action
        ):
            # Un documento por vencer no habilita el pase a LISTO_PARA_TRABAJAR:
            # el aviso tiene que pedir explícitamente el reemplazo.
            notifications.notify(
                event_type=NotificationEventType.DOCUMENT_EXPIRING_SOON.value,
                users=portal_users,
                title="Documento próximo a vencer",
                body=(
                    f"Tu documento {document.type} vence el {document.expires_at}. "
                    "Subí uno vigente desde el portal para poder continuar con el onboarding."
                ),
                payload={"document_id": document.id, "client_id": client.id},
            )

        from app.services.client_onboarding_status import sync_client_onboarding_status

        sync_client_onboarding_status(db, client)
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
