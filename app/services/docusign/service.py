"""Integración DocuSign — cuenta empresa (env) y envío de contratos."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings, get_settings
from app.models.client import Client
from app.models.docusign_envelope import DocusignEnvelope
from app.models.enums import NotificationEventType
from app.models.user import User
from app.schemas.docusign import (
    DocusignConnectionResponse,
    DocusignConsentUrlResponse,
    DocusignEnvelopeResponse,
    DocusignSendEnvelopeRequest,
    DocusignSendEnvelopeResponse,
    DocusignTemplateDetailResponse,
    DocusignTemplateResponse,
    DocusignTemplateRoleResponse,
    DocusignWebhookUrlResponse,
)
from app.services.clients import ClientService
from app.services.docusign.client import DocusignApiError, DocusignClient
from app.services.docusign.webhook import (
    DocusignConnectEvent,
    parse_connect_payload,
    verify_connect_signature,
)
from app.services.notifications import NotificationService
from app.services.storage import get_storage_provider

logger = logging.getLogger(__name__)

DOCUSIGN_ROLES = frozenset({"ADMIN", "SALES_REP"})
DOCUSIGN_TERMINAL_STATUSES = frozenset({"completed", "declined", "voided"})
DOCUSIGN_SENT_DOCUMENT_STATUSES = frozenset({"sent", "delivered", "completed"})


class DocusignService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.notifications = NotificationService(db)

    @staticmethod
    def ensure_access(actor: User) -> None:
        if actor.role.code not in DOCUSIGN_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene acceso a contratos DocuSign",
            )

    @staticmethod
    def _map_connection(settings: Settings) -> DocusignConnectionResponse:
        return DocusignConnectionResponse(
            connected=settings.docusign_configured,
            account_id=settings.docusign_account_id or None,
            auth_server=settings.docusign_auth_server or None,
            default_template_id=settings.docusign_default_template_id or None,
            default_template_role_name=settings.docusign_default_template_role_name or None,
        )

    def _client_from_settings(self) -> DocusignClient:
        settings = self.settings
        if not settings.docusign_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "DocuSign no está configurado en el servidor. "
                    "Definí DOCUSIGN_* en las variables de entorno."
                ),
            )
        return DocusignClient(
            integration_key=settings.docusign_integration_key,
            impersonated_user_id=settings.docusign_user_id,
            account_id=settings.docusign_account_id,
            private_key_pem=settings.docusign_private_key,
            base_uri=settings.docusign_base_uri,
            auth_server=settings.docusign_auth_server,
        )

    def get_connection(self, actor: User) -> DocusignConnectionResponse:
        self.ensure_access(actor)
        return self._map_connection(self.settings)

    def get_consent_url(self, actor: User) -> DocusignConsentUrlResponse:
        self.ensure_access(actor)
        if not self.settings.docusign_integration_key.strip():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DocuSign no está configurado en el servidor",
            )
        redirect_uri = f"{self.settings.portal_base_url}/contratos"
        consent_url = DocusignClient.consent_url(
            integration_key=self.settings.docusign_integration_key,
            auth_server=self.settings.docusign_auth_server,
            redirect_uri=redirect_uri,
        )
        return DocusignConsentUrlResponse(consent_url=consent_url, redirect_uri=redirect_uri)

    def get_webhook_url(self, actor: User) -> DocusignWebhookUrlResponse:
        self.ensure_access(actor)
        webhook_url = self.settings.docusign_webhook_url
        if not webhook_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Definí BACKEND_PUBLIC_URL en el servidor (URL pública del backend para DocuSign Connect)",
            )
        hmac_ok = bool(self.settings.docusign_connect_hmac_key.strip())
        return DocusignWebhookUrlResponse(
            webhook_url=webhook_url,
            connect_hmac_configured=hmac_ok,
            instructions=(
                "DocuSign → Settings → Connect → Add Configuration. "
                "Pegá esta URL, formato JSON, evento Envelope Completed. "
                "Copiá el HMAC secret a DOCUSIGN_CONNECT_HMAC_KEY."
            ),
        )

    def _resolve_client_id(self, client_id: int | None, signer_email: str) -> int | None:
        if client_id is not None:
            return client_id
        normalized = signer_email.strip().lower()
        if not normalized:
            return None
        matched = self.db.execute(
            select(Client.id).where(func.lower(Client.email) == normalized)
        ).scalar_one_or_none()
        return matched

    def link_envelopes_to_clients_by_email(self) -> int:
        """Vincula contratos existentes sin client_id cuando el email coincide con un cliente."""
        rows = self.db.execute(
            select(DocusignEnvelope).where(DocusignEnvelope.client_id.is_(None))
        ).scalars().all()
        linked = 0
        for row in rows:
            client_id = self._resolve_client_id(None, row.signer_email)
            if client_id is not None:
                row.client_id = client_id
                linked += 1
        if linked:
            self.db.commit()
        return linked

    def sync_all_envelopes_from_docusign(self, *, notify: bool = False) -> dict[str, int]:
        """Sincroniza todos los contratos con DocuSign y archiva PDFs firmados."""
        api_client = self._client_from_settings()
        rows = self.db.execute(select(DocusignEnvelope)).scalars().all()
        stats = {"total": len(rows), "updated": 0, "completed": 0, "pdfs": 0, "linked": 0}
        stats["linked"] = self.link_envelopes_to_clients_by_email()

        for row in rows:
            try:
                remote = api_client.get_envelope(row.docusign_envelope_id)
            except DocusignApiError:
                continue
            if self._apply_remote_status(row, remote, notify=notify):
                stats["updated"] += 1
            if row.status.lower() == "completed":
                if not row.signed_storage_key:
                    self._persist_signed_pdf(row)
                    if row.signed_storage_key:
                        stats["pdfs"] += 1

        stats["completed"] = sum(1 for row in rows if row.status.lower() == "completed")
        self.db.commit()
        return stats

    def _docusign_http_error(self, exc: DocusignApiError) -> HTTPException:
        if exc.status_code == 400 and "consentimiento" in str(exc).lower():
            return HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    def _resolve_effective_status(
        self,
        api_client: DocusignClient,
        row: DocusignEnvelope,
        remote: dict[str, Any],
    ) -> tuple[str, datetime | None]:
        envelope_status = (remote.get("status") or row.status or "sent").lower()
        signed_at: datetime | None = None

        try:
            signer_info = api_client.get_signer_status(
                row.docusign_envelope_id,
                role_name=row.template_role_name,
                signer_email=row.signer_email,
            )
        except DocusignApiError:
            return envelope_status, None

        recipient_status = (signer_info.get("status") or "").lower()
        if recipient_status in {"completed", "signed"}:
            signed_at = signer_info.get("signed_at")
            return "completed", signed_at
        if recipient_status == "declined":
            return "declined", None
        if recipient_status == "delivered":
            return "delivered", None

        return envelope_status, None

    def _signer_has_completed(self, api_client: DocusignClient, row: DocusignEnvelope) -> bool:
        try:
            signer_info = api_client.get_signer_status(
                row.docusign_envelope_id,
                role_name=row.template_role_name,
                signer_email=row.signer_email,
            )
        except DocusignApiError:
            return False
        return (signer_info.get("status") or "").lower() in {"completed", "signed"}

    def list_templates(self, actor: User) -> list[DocusignTemplateResponse]:
        self.ensure_access(actor)
        client = self._client_from_settings()
        try:
            templates = client.list_templates()
        except DocusignApiError as exc:
            raise self._docusign_http_error(exc) from exc

        return [
            DocusignTemplateResponse(
                template_id=item.get("templateId") or "",
                name=item.get("name") or "Sin nombre",
                description=item.get("description"),
            )
            for item in templates
            if item.get("templateId")
        ]

    def get_template_detail(self, actor: User, template_id: str) -> DocusignTemplateDetailResponse:
        self.ensure_access(actor)
        client = self._client_from_settings()
        try:
            detail = client.get_template(template_id)
        except DocusignApiError as exc:
            raise self._docusign_http_error(exc) from exc

        roles: list[DocusignTemplateRoleResponse] = []
        for recipient in detail.get("recipients", {}).get("signers") or []:
            role_name = recipient.get("roleName")
            if role_name:
                roles.append(
                    DocusignTemplateRoleResponse(
                        role_name=role_name,
                        recipient_type=recipient.get("recipientType"),
                    )
                )

        return DocusignTemplateDetailResponse(
            template_id=detail.get("templateId") or template_id,
            name=detail.get("name") or "Sin nombre",
            description=detail.get("description"),
            roles=roles,
        )

    def _map_envelope(self, row: DocusignEnvelope) -> DocusignEnvelopeResponse:
        client_name = None
        if row.client:
            client_name = f"{row.client.first_name} {row.client.last_name}".strip()
        sent_by_name = None
        if row.sent_by:
            sent_by_name = f"{row.sent_by.first_name} {row.sent_by.last_name}".strip()
        return DocusignEnvelopeResponse(
            id=row.id,
            docusign_envelope_id=row.docusign_envelope_id,
            signer_name=row.signer_name,
            signer_email=row.signer_email,
            template_id=row.template_id,
            template_role_name=row.template_role_name,
            subject=row.subject,
            status=row.status,
            client_id=row.client_id,
            client_name=client_name,
            sent_by_user_id=row.sent_by_user_id,
            sent_by_name=sent_by_name,
            sent_at=row.sent_at,
            completed_at=row.completed_at,
            has_signed_document=bool(row.signed_storage_key),
        )

    def _envelopes_query(self, actor: User):
        query = (
            select(DocusignEnvelope)
            .options(
                joinedload(DocusignEnvelope.client),
                joinedload(DocusignEnvelope.sent_by),
            )
            .order_by(DocusignEnvelope.sent_at.desc())
        )
        if actor.role.code == "SALES_REP":
            query = query.where(DocusignEnvelope.sent_by_user_id == actor.id)
        return query

    def list_envelopes(self, actor: User) -> list[DocusignEnvelopeResponse]:
        self.ensure_access(actor)
        rows = self.db.execute(self._envelopes_query(actor)).unique().scalars().all()
        return [self._map_envelope(row) for row in rows]

    def list_client_envelopes(self, actor: User, client_id: int) -> list[DocusignEnvelopeResponse]:
        self.ensure_access(actor)
        client = ClientService(self.db).get_client_for_user(actor, client_id)
        if client is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")

        query = self._envelopes_query(actor).where(DocusignEnvelope.client_id == client_id)
        rows = self.db.execute(query).unique().scalars().all()
        return [self._map_envelope(row) for row in rows]

    def _get_envelope_row(self, actor: User, envelope_id: int) -> DocusignEnvelope:
        row = self.db.execute(
            select(DocusignEnvelope)
            .options(joinedload(DocusignEnvelope.client), joinedload(DocusignEnvelope.sent_by))
            .where(DocusignEnvelope.id == envelope_id)
        ).unique().scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrato no encontrado")
        if actor.role.code == "SALES_REP" and row.sent_by_user_id != actor.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puede acceder a este contrato")
        return row

    def _get_envelope_by_docusign_id(self, docusign_envelope_id: str) -> DocusignEnvelope | None:
        return self.db.execute(
            select(DocusignEnvelope)
            .options(joinedload(DocusignEnvelope.client), joinedload(DocusignEnvelope.sent_by))
            .where(DocusignEnvelope.docusign_envelope_id == docusign_envelope_id)
        ).unique().scalar_one_or_none()

    def _signed_filename(self, row: DocusignEnvelope) -> str:
        safe_name = self._safe_signer_slug(row)
        return f"contrato-{safe_name}-{row.id}.pdf"

    def _sent_filename(self, row: DocusignEnvelope) -> str:
        safe_name = self._safe_signer_slug(row)
        return f"contrato-enviado-{safe_name}-{row.id}.pdf"

    @staticmethod
    def _safe_signer_slug(row: DocusignEnvelope) -> str:
        return "".join(
            char if char.isalnum() or char in ("-", "_") else "-"
            for char in row.signer_name.strip().lower().replace(" ", "-")
        ) or "firmante"

    def _signed_storage_key(self, row: DocusignEnvelope) -> str:
        storage = get_storage_provider()
        if row.client_id:
            return storage.build_key(
                "clients",
                str(row.client_id),
                "contracts",
                str(row.id),
                "signed.pdf",
            )
        return storage.build_key("docusign", "envelopes", str(row.id), "signed.pdf")

    def _persist_signed_pdf(self, row: DocusignEnvelope) -> None:
        if row.signed_storage_key:
            return
        api_client = self._client_from_settings()
        try:
            content = api_client.download_combined_document(row.docusign_envelope_id)
        except DocusignApiError as exc:
            logger.warning(
                "No se pudo descargar PDF firmado para envelope %s: %s",
                row.docusign_envelope_id,
                exc,
            )
            return

        filename = self._signed_filename(row)
        storage_key = self._signed_storage_key(row)
        storage = get_storage_provider()
        try:
            storage.put_object(storage_key, content, "application/pdf")
        except Exception:
            logger.exception(
                "No se pudo archivar PDF firmado en S3 para envelope %s",
                row.docusign_envelope_id,
            )
            return
        row.signed_storage_key = storage_key
        row.signed_document_filename = filename

    def _notify_envelope_completed(self, row: DocusignEnvelope) -> None:
        if row.completion_notified_at is not None:
            return
        recipient = row.sent_by
        if recipient is None or recipient.id is None:
            return

        client_label = row.signer_name
        if row.client:
            client_label = f"{row.client.first_name} {row.client.last_name}".strip()

        self.notifications.notify(
            event_type=NotificationEventType.DOCUSIGN_ENVELOPE_COMPLETED.value,
            users=[recipient],
            title="Contrato firmado",
            body=f"{client_label} firmó el contrato «{row.subject}».",
            payload={
                "client_id": row.client_id,
                "envelope_id": row.id,
                "signer_name": row.signer_name,
                "signer_email": row.signer_email,
            },
            commit=True,
        )
        row.completion_notified_at = datetime.now(timezone.utc)

    def _needs_completion_finalize(self, row: DocusignEnvelope) -> bool:
        if row.status.lower() != "completed":
            return False
        return not row.signed_storage_key or row.completion_notified_at is None

    def _finalize_status_change(self, row: DocusignEnvelope, *, notify: bool) -> None:
        if row.status.lower() != "completed":
            return
        if row.completed_at is None:
            row.completed_at = datetime.now(timezone.utc)
        self._persist_signed_pdf(row)
        if notify:
            self._notify_envelope_completed(row)

    def _apply_remote_status(
        self,
        row: DocusignEnvelope,
        remote: dict,
        *,
        notify: bool,
        api_client: DocusignClient | None = None,
    ) -> bool:
        if api_client is None:
            api_client = self._client_from_settings()
        previous_status = row.status.lower()
        effective_status, signed_at = self._resolve_effective_status(api_client, row, remote)
        row.status = effective_status
        row.last_status_sync_at = datetime.now(timezone.utc)
        current_status = row.status.lower()
        if current_status == "completed":
            row.completed_at = signed_at or row.completed_at or row.last_status_sync_at
        if current_status == "completed" and previous_status != "completed":
            self._finalize_status_change(row, notify=notify)
            return True
        return previous_status != current_status

    def _apply_connect_event(self, row: DocusignEnvelope, event: DocusignConnectEvent, *, notify: bool) -> bool:
        previous_status = row.status.lower()
        row.status = event.status
        row.last_status_sync_at = datetime.now(timezone.utc)
        if row.status.lower() == "completed" and row.completed_at is None:
            row.completed_at = row.last_status_sync_at
        if row.status.lower() == "completed" and previous_status != "completed":
            self._finalize_status_change(row, notify=notify)
            return True
        return previous_status != row.status.lower()

    def handle_connect_webhook(
        self,
        body: bytes,
        *,
        signature: str | None,
        content_type: str | None,
    ) -> dict[str, str | bool]:
        allow_missing_hmac = self.settings.is_development and not self.settings.docusign_connect_hmac_key.strip()
        if not verify_connect_signature(
            body,
            signature,
            self.settings.docusign_connect_hmac_key,
            allow_missing=allow_missing_hmac,
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Firma HMAC inválida")

        event = parse_connect_payload(body, content_type)
        if event is None:
            logger.warning("DocuSign Connect: evento no parseable")
            return {"received": True, "processed": False}

        row = self._get_envelope_by_docusign_id(event.envelope_id)
        if row is None:
            logger.info("DocuSign Connect: envelope %s no registrado en CRM", event.envelope_id)
            return {"received": True, "processed": False}

        changed = self._apply_connect_event(row, event, notify=True)
        if self._needs_completion_finalize(row):
            self._finalize_status_change(
                row,
                notify=row.completion_notified_at is None,
            )
            changed = True
        if changed or row.status.lower() == "completed":
            self.db.commit()
        return {"received": True, "processed": changed, "envelope_id": event.envelope_id}

    def sync_pending_envelopes(self, actor: User) -> list[DocusignEnvelopeResponse]:
        self.ensure_access(actor)
        query = self._envelopes_query(actor)
        rows = self.db.execute(query).unique().scalars().all()
        pending = [row for row in rows if row.status.lower() not in DOCUSIGN_TERMINAL_STATUSES]
        needs_finalize = [row for row in rows if self._needs_completion_finalize(row)]

        if not pending and not needs_finalize:
            return [self._map_envelope(row) for row in rows]

        api_client = self._client_from_settings()
        changed = False
        for row in pending:
            try:
                remote = api_client.get_envelope(row.docusign_envelope_id)
            except DocusignApiError:
                continue
            if self._apply_remote_status(row, remote, notify=True):
                changed = True
            elif self._needs_completion_finalize(row):
                self._finalize_status_change(
                    row,
                    notify=row.completion_notified_at is None,
                )
                changed = True

        for row in needs_finalize:
            if row in pending:
                continue
            self._finalize_status_change(
                row,
                notify=row.completion_notified_at is None,
            )
            changed = True

        if changed:
            self.db.commit()
            rows = self.db.execute(query).unique().scalars().all()

        return [self._map_envelope(row) for row in rows]

    def get_sent_document(self, actor: User, envelope_id: int) -> tuple[bytes, str]:
        row = self._get_envelope_row(actor, envelope_id)
        envelope_status = row.status.lower()
        if envelope_status not in DOCUSIGN_SENT_DOCUMENT_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El contrato enviado no está disponible en este estado",
            )

        api_client = self._client_from_settings()
        try:
            content = api_client.download_primary_document(row.docusign_envelope_id)
        except DocusignApiError as exc:
            raise self._docusign_http_error(exc) from exc

        return content, self._sent_filename(row)

    def get_signed_document(self, actor: User, envelope_id: int) -> tuple[bytes, str]:
        row = self._get_envelope_row(actor, envelope_id)
        api_client = self._client_from_settings()
        is_completed = row.status.lower() == "completed" or self._signer_has_completed(api_client, row)
        if not is_completed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El contrato aún no está firmado",
            )

        if row.signed_storage_key:
            storage = get_storage_provider()
            content, _ = storage.get_object_bytes(row.signed_storage_key)
            filename = row.signed_document_filename or self._signed_filename(row)
            return content, filename

        api_client = self._client_from_settings()
        try:
            content = api_client.download_combined_document(row.docusign_envelope_id)
        except DocusignApiError as exc:
            raise self._docusign_http_error(exc) from exc

        try:
            self._persist_signed_pdf(row)
            self.db.commit()
        except Exception:
            logger.exception("No se pudo persistir PDF firmado para envelope %s", row.id)

        filename = row.signed_document_filename or self._signed_filename(row)
        return content, filename

    def send_envelope(
        self, actor: User, payload: DocusignSendEnvelopeRequest
    ) -> DocusignSendEnvelopeResponse:
        self.ensure_access(actor)
        client = self._client_from_settings()
        settings = self.settings

        template_id = payload.template_id or settings.docusign_default_template_id
        role_name = payload.template_role_name or settings.docusign_default_template_role_name
        if not template_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Seleccioná una plantilla o configurá DOCUSIGN_DEFAULT_TEMPLATE_ID",
            )

        try:
            template_detail = client.get_template(template_id)
        except DocusignApiError as exc:
            raise self._docusign_http_error(exc) from exc

        valid_roles = [
            recipient.get("roleName")
            for recipient in template_detail.get("recipients", {}).get("signers") or []
            if recipient.get("roleName")
        ]
        if not valid_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La plantilla DocuSign no tiene roles de firmante configurados",
            )
        if role_name not in valid_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"El rol «{role_name}» no existe en la plantilla. "
                    f"Roles válidos: {', '.join(valid_roles)}"
                ),
            )
        if len(valid_roles) > 1:
            logger.warning(
                "Plantilla %s tiene %s roles (%s); se enviará solo «%s»",
                template_id,
                len(valid_roles),
                ", ".join(valid_roles),
                role_name,
            )

        if payload.client_id is not None:
            client_row = self.db.get(Client, payload.client_id)
            if client_row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")

        resolved_client_id = self._resolve_client_id(
            payload.client_id,
            str(payload.signer_email),
        )

        try:
            result = client.create_envelope_from_template(
                template_id=template_id,
                role_name=role_name,
                signer_name=payload.signer_name,
                signer_email=str(payload.signer_email),
                subject=payload.subject,
                text_tabs=payload.text_tabs,
            )
        except DocusignApiError as exc:
            raise self._docusign_http_error(exc) from exc

        envelope_id = result.get("envelopeId")
        if not envelope_id:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="DocuSign no devolvió envelopeId",
            )

        row = DocusignEnvelope(
            docusign_envelope_id=envelope_id,
            sent_by_user_id=actor.id,
            client_id=resolved_client_id,
            signer_name=payload.signer_name.strip(),
            signer_email=str(payload.signer_email).strip().lower(),
            template_id=template_id,
            template_role_name=role_name,
            subject=payload.subject.strip(),
            status=result.get("status") or "sent",
            sent_at=datetime.now(timezone.utc),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        row = self.db.execute(
            select(DocusignEnvelope)
            .options(joinedload(DocusignEnvelope.client), joinedload(DocusignEnvelope.sent_by))
            .where(DocusignEnvelope.id == row.id)
        ).unique().scalar_one()

        return DocusignSendEnvelopeResponse(envelope=self._map_envelope(row))

    def sync_envelope_status(self, actor: User, envelope_id: int) -> DocusignEnvelopeResponse:
        self.ensure_access(actor)
        row = self._get_envelope_row(actor, envelope_id)

        api_client = self._client_from_settings()
        try:
            remote = api_client.get_envelope(row.docusign_envelope_id)
        except DocusignApiError as exc:
            raise self._docusign_http_error(exc) from exc

        self._apply_remote_status(row, remote, notify=True)
        if self._needs_completion_finalize(row):
            self._finalize_status_change(
                row,
                notify=row.completion_notified_at is None,
            )
        self.db.commit()
        self.db.refresh(row)
        return self._map_envelope(row)
