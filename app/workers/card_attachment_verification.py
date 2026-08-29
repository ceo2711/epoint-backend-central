"""Verificación IA de adjuntos del tablero — reportes Equifax, Experian, etc."""

import json
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.database import SessionLocal
from app.models.board_card import BoardCard
from app.models.board_list import BoardList
from app.models.card_attachment import CardAttachment
from app.models.card_attachment_verification import CardAttachmentVerification
from app.models.client import Client
from app.models.enums import DocumentVerificationStatus, NotificationEventType
from app.models.user import User
from app.services.board_attachment_verification_messages import (
    build_board_approval_messages,
    build_board_rejection_messages,
)
from app.services.document_verification_messages import system_verification_failure_result
from app.services.board_attachment_verification_rules import (
    apply_report_date_freshness,
    build_board_attachment_context,
    is_board_attachment_approved,
    resolve_attachment_kind,
)
from app.services.notifications import NotificationService
from app.services.storage import get_storage_provider

logger = logging.getLogger(__name__)

VERIFICATION_PROMPT = """Analyze the uploaded file for board task verification and respond ONLY with valid JSON:
{
  "is_readable": true/false,
  "is_complete": true/false,
  "is_recent": true/false,
  "report_date": "YYYY-MM-DD or null",
  "document_type_matches": true/false,
  "detected_document_type": "short label of what the file actually is",
  "detected_bureau": "Experian|Equifax|TransUnion|Clarity|Innovis|ChexSystems|other|null",
  "name_matches": true/false,
  "rejection_reasons": [{"en": "English reason", "es": "Motivo en español"}],
  "approval_reasons": [{"en": "English detail", "es": "Detalle en español"}]
}

Critical rules:
- document_type_matches is the most important field. Set false if the file is NOT the expected report type.
- detected_document_type and detected_bureau must describe what you actually see, not what was requested.
- name_matches: true only if the client's full name (or clear partial match) appears on the report.
- is_recent: true ONLY if the report date is within the last 15 days INCLUDING today's date from the context block. A report dated today is recent — never treat today's date as future. If the report date is older than 15 days, set is_recent=false and reject — the client must upload a newly generated report. If no date is visible, set is_recent=false unless the file clearly looks like a freshly generated official portal download (prefer rejecting when freshness cannot be confirmed).
- is_complete: true if tradelines/accounts section is visible (for credit reports) or all expected sections are present.
- For PDF credit reports, color is NOT required — focus on readability and correct bureau branding.
- Every reason must include both "en" and "es".
- If rejected, rejection_reasons must explain the main issue (wrong bureau, wrong document type, missing name, outdated report older than 15 days, etc.).
- If approved, approval_reasons must cite verified facts — never claim a match that is false."""


def run_card_attachment_verification(attachment_id: int) -> dict:
    db = SessionLocal()
    try:
        attachment = db.get(
            CardAttachment,
            attachment_id,
            options=[
                joinedload(CardAttachment.card)
                .joinedload(BoardCard.board_list)
                .joinedload(BoardList.board),
            ],
        )
        if attachment is None:
            logger.error("Adjunto %s no encontrado para verificación", attachment_id)
            return {"error": "attachment not found"}

        card = attachment.card
        board_list = card.board_list
        client = db.get(Client, board_list.board.client_id)
        if client is None:
            logger.error("Cliente no encontrado para adjunto %s", attachment_id)
            return {"error": "client not found"}

        previous_status = attachment.verification_status

        if attachment.verification_status == DocumentVerificationStatus.PENDIENTE.value:
            attachment.verification_status = DocumentVerificationStatus.EN_PROCESO.value
            db.commit()

        storage = get_storage_provider()
        file_bytes, media_type = storage.get_object_bytes(attachment.storage_key)

        from app.services.llm import get_llm_service

        llm = get_llm_service()
        client_name = f"{client.first_name} {client.last_name}".strip()
        attachment_kind = resolve_attachment_kind(
            card_title=card.title,
            list_title=board_list.title,
            requires_file_upload=card.requires_file_upload,
        )
        today = date.today()
        type_context = build_board_attachment_context(
            attachment_kind=attachment_kind,
            client_name=client_name,
            card_title=card.title,
            list_title=board_list.title,
            today=today,
        )
        try:
            result_text = llm.analyze_document_bytes(
                content=file_bytes,
                media_type=attachment.mime_type or media_type,
                prompt=f"{VERIFICATION_PROMPT}\n\n{type_context}",
            )
            result = json.loads(result_text.strip().removeprefix("```json").removesuffix("```").strip())
        except Exception:
            logger.exception("Error verificando adjunto %s", attachment_id)
            result = system_verification_failure_result()

        apply_report_date_freshness(result, today)
        approved = is_board_attachment_approved(result, attachment_kind)

        if approved:
            approval_messages = build_board_approval_messages(
                result,
                attachment_kind=attachment_kind,
                client_name=client_name,
            )
            rejection_messages = []
            status = DocumentVerificationStatus.APROBADO.value
        else:
            approval_messages = []
            rejection_messages = build_board_rejection_messages(
                result,
                attachment_kind=attachment_kind,
                client_name=client_name,
            )
            status = DocumentVerificationStatus.RECHAZADO.value

        attachment.verification_status = status

        verification = CardAttachmentVerification(
            attachment_id=attachment.id,
            status=attachment.verification_status,
            ai_model=llm.model_name if llm.is_available else "unavailable",
            raw_response=result,
            rejection_reasons=rejection_messages or None,
            approval_reasons=approval_messages or None,
        )
        db.add(verification)

        notifications = NotificationService(db)
        portal_users = list(db.execute(select(User).where(User.client_id == client.id)).scalars().all())

        if not approved and portal_users and previous_status != DocumentVerificationStatus.RECHAZADO.value:
            rejection_es = [item["es"] for item in rejection_messages]
            notifications.notify(
                event_type=NotificationEventType.BOARD_ATTACHMENT_REJECTED.value,
                users=portal_users,
                title="Archivo del tablero rechazado",
                body=(
                    f"Tu archivo '{attachment.original_filename}' en '{card.title}' no pasó la verificación: "
                    f"{', '.join(rejection_es) or 'revisar calidad'}"
                ),
                payload={
                    "attachment_id": attachment.id,
                    "card_id": card.id,
                    "client_id": client.id,
                },
            )

        db.commit()

        return {"attachment_id": attachment_id, "status": attachment.verification_status}
    except Exception:
        logger.exception("Fallo crítico verificando adjunto %s", attachment_id)
        try:
            attachment = db.get(CardAttachment, attachment_id)
            if attachment and attachment.verification_status:
                attachment.verification_status = DocumentVerificationStatus.RECHAZADO.value
                db.commit()
        except Exception:
            logger.exception("No se pudo marcar adjunto %s como rechazado", attachment_id)
        raise
    finally:
        db.close()
