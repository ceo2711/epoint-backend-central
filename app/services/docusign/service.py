"""Integración DocuSign — cuenta empresa (env) y envío de contratos."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings, get_settings
from app.models.client import Client
from app.models.docusign_envelope import DocusignEnvelope
from app.models.enums import NotificationEventType
from app.models.notification import Notification
from app.models.role import Role
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
    normalize_docusign_status,
    parse_connect_payload,
    verify_connect_signature,
)
from app.services.notifications import NotificationService
from app.services.role_access import (
    AREA_LEADER_ROLE,
    SALES_AREA_CODE,
    can_access_docusign,
    can_manage_onboarding,
    SALES_STAFF_ROLES,
    can_supervise_sales_reps,
    is_sales_area_leader,
    is_sales_staff,
)
from app.services.storage import get_storage_provider

logger = logging.getLogger(__name__)

DOCUSIGN_ROLES = frozenset({"ADMIN", "BRANCH_MANAGER", "SALES_REP", "SUB_SELLER", "AREA_LEADER"})
DOCUSIGN_TERMINAL_STATUSES = frozenset({"completed", "declined", "voided"})
DOCUSIGN_SENT_DOCUMENT_STATUSES = frozenset({"sent", "delivered", "completed"})
PREFERRED_TEMPLATE_ROLE_NAMES = ("Cliente", "Client", "Signer", "Firmante")


def resolve_template_role_name(requested: str | None, valid_roles: list[str]) -> str:
    """Elige un rol válido de la plantilla; tolera defaults desactualizados (Signer vs Cliente)."""
    if not valid_roles:
        raise ValueError("La plantilla DocuSign no tiene roles de firmante configurados")

    requested_norm = (requested or "").strip()
    if requested_norm in valid_roles:
        return requested_norm

    if requested_norm:
        for role in valid_roles:
            if role.lower() == requested_norm.lower():
                return role

    lower_map = {role.lower(): role for role in valid_roles}
    for preferred in PREFERRED_TEMPLATE_ROLE_NAMES:
        match = lower_map.get(preferred.lower())
        if match:
            if requested_norm and requested_norm != match:
                logger.info(
                    "Rol DocuSign «%s» no está en la plantilla; usando «%s»",
                    requested_norm,
                    match,
                )
            return match

    if len(valid_roles) == 1:
        only = valid_roles[0]
        if requested_norm and requested_norm != only:
            logger.info(
                "Rol DocuSign «%s» no está en la plantilla; usando el único rol «%s»",
                requested_norm,
                only,
            )
        return only

    if requested_norm:
        logger.warning(
            "Rol DocuSign «%s» no válido (%s); usando «%s»",
            requested_norm,
            ", ".join(valid_roles),
            valid_roles[0],
        )
    return valid_roles[0]


class DocusignService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.notifications = NotificationService(db)
        self._pending_in_app_notifications: list[Notification] = []

    @staticmethod
    def ensure_access(actor: User) -> None:
        if can_access_docusign(actor):
            return
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

    @staticmethod
    def _parse_signer_name(signer_name: str) -> tuple[str, str]:
        parts = signer_name.strip().split()
        if len(parts) >= 2:
            return parts[0], " ".join(parts[1:])
        if parts:
            return parts[0], ""
        return "Firmante", ""

    @staticmethod
    def _client_matches_signer(client: Client, signer_name: str, signer_email: str) -> bool:
        if client.email.lower().strip() != signer_email.lower().strip():
            return False
        first, last = DocusignService._parse_signer_name(signer_name)
        if client.full_name.lower().strip() == signer_name.lower().strip():
            return True
        return (
            client.first_name.lower().strip() == first.lower().strip()
            and client.last_name.lower().strip() == last.lower().strip()
        )

    def _find_client_for_signer(self, signer_name: str, signer_email: str) -> Client | None:
        normalized_email = signer_email.lower().strip()
        candidates = self.db.execute(
            select(Client).where(func.lower(Client.email) == normalized_email)
        ).scalars().all()
        for client in candidates:
            if self._client_matches_signer(client, signer_name, signer_email):
                return client
        return None

    def _ensure_client_for_completed_envelope(self, row: DocusignEnvelope) -> bool:
        """Elimina vínculos incorrectos; el alta en CRM es manual desde la UI."""
        if row.status.lower() != "completed":
            return False

        previous_client_id = row.client_id
        if row.client_id is not None:
            linked = self.db.get(Client, row.client_id)
            if linked is None or not self._client_matches_signer(
                linked, row.signer_name, row.signer_email
            ):
                row.client_id = None

        changed = previous_client_id != row.client_id
        if changed and row.signed_storage_key:
            row.signed_storage_key = None
            row.signed_document_filename = None
        return changed

    def _envelope_client_registered(self, row: DocusignEnvelope) -> bool:
        if not row.client_id or not row.client:
            return False
        return self._client_matches_signer(row.client, row.signer_name, row.signer_email)

    def register_client_from_envelope(
        self,
        actor: User,
        envelope_id: int,
        *,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        source: str,
        merchant_id: int,
        active_merchant_id: int,
    ) -> tuple[DocusignEnvelope, Client]:
        self.ensure_access(actor)
        row = self._get_envelope_row(actor, envelope_id, merchant_id=active_merchant_id)
        if row.status.lower() != "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El contrato debe estar firmado para registrar al cliente",
            )
        if self._envelope_client_registered(row):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este contrato ya tiene un cliente registrado en el CRM",
            )

        if row.prospect_id is not None:
            from app.models.prospect import Prospect
            from app.services.prospects import CONVERSION_REQUIREMENTS_DETAIL, ProspectService

            prospect = self.db.get(Prospect, row.prospect_id)
            if prospect is not None:
                if prospect.converted_client_id is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Este contrato ya está vinculado a un cliente vía el prospecto",
                    )
                psvc = ProspectService(self.db)
                if not psvc._ready_for_conversion(prospect):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=CONVERSION_REQUIREMENTS_DETAIL,
                    )
                client = psvc.convert_to_client(prospect=prospect, actor=actor)
                row = self._get_envelope_row(actor, envelope_id)
                return row, client

        client_service = ClientService(self.db)
        resolved_merchant_id = merchant_id or row.merchant_id or active_merchant_id
        new_client, _portal_pw = client_service.create_client(
            actor=actor,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            source=source,
            merchant_id=resolved_merchant_id,
            commit=False,
        )
        signed_at = row.completed_at or datetime.now(timezone.utc)
        new_client.docusign_contract_signed_at = signed_at
        new_client.docusign_envelope_id = row.id
        row.client_id = new_client.id

        if row.signed_storage_key:
            row.signed_storage_key = None
            row.signed_document_filename = None
        self._persist_signed_pdf(row)

        self.db.commit()
        if _portal_pw is not None:
            client_service._send_client_portal_welcome(new_client, _portal_pw)
        row = self._get_envelope_row(actor, envelope_id)
        client = self.db.get(Client, new_client.id)
        if client is None:
            raise HTTPException(status_code=500, detail="Error al registrar cliente")
        return row, client

    def get_client_signed_contract(
        self, actor: User, client_id: int
    ) -> tuple[bytes, str]:
        client_service = ClientService(self.db)
        if not client_service.user_can_access_client(actor, client_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
        client = client_service.get_client_detail(client_id)
        if client is None or not client.docusign_envelope_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Este cliente no tiene contrato firmado vinculado",
            )
        row = self.db.execute(
            select(DocusignEnvelope).where(DocusignEnvelope.id == client.docusign_envelope_id)
        ).scalar_one_or_none()
        if row is None or row.status.lower() != "completed":
            raise HTTPException(status_code=404, detail="Contrato no encontrado o no firmado")

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
        filename = row.signed_document_filename or self._signed_filename(row)
        return content, filename

    def repair_envelope_client_links(self) -> int:
        """Corrige vínculos incorrectos en contratos ya firmados."""
        rows = self.db.execute(
            select(DocusignEnvelope)
            .options(joinedload(DocusignEnvelope.client), joinedload(DocusignEnvelope.sent_by))
            .where(DocusignEnvelope.status == "completed")
        ).unique().scalars().all()
        repaired = 0
        for row in rows:
            if self._ensure_client_for_completed_envelope(row):
                repaired += 1
                if not row.signed_storage_key:
                    self._persist_signed_pdf(row)
        if repaired:
            self.db.commit()
        return repaired

    def sync_all_envelopes_from_docusign(self, *, notify: bool = False) -> dict[str, int]:
        """Sincroniza todos los contratos con DocuSign y archiva PDFs firmados."""
        api_client = self._client_from_settings()
        rows = self.db.execute(select(DocusignEnvelope)).scalars().all()
        stats = {"total": len(rows), "updated": 0, "completed": 0, "pdfs": 0, "linked": 0}
        stats["linked"] = self.repair_envelope_client_links()

        for row in rows:
            try:
                remote = api_client.get_envelope(row.docusign_envelope_id)
            except DocusignApiError:
                continue
            if self._apply_remote_status(row, remote):
                stats["updated"] += 1
            if normalize_docusign_status(row.status) == "completed":
                if self._process_completed_envelope(row, allow_notify=notify):
                    stats["updated"] += 1
                if row.signed_storage_key:
                    stats["pdfs"] += 1

        stats["completed"] = sum(1 for row in rows if row.status.lower() == "completed")
        if notify:
            self._commit_docusign_changes()
        else:
            self.db.commit()
        return stats

    def _docusign_http_error(self, exc: DocusignApiError) -> HTTPException:
        if exc.status_code == 400 and "consentimiento" in str(exc).lower():
            return HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )
        if exc.status_code == 429:
            return HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="DocuSign limitó las consultas de estado. El contrato se actualizará por webhook o puedes reintentar más tarde.",
            )
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    def _resolve_effective_status(
        self,
        api_client: DocusignClient,
        row: DocusignEnvelope,
        remote: dict[str, Any],
    ) -> tuple[str, datetime | None]:
        envelope_status = normalize_docusign_status(remote.get("status") or row.status or "sent")
        signed_at: datetime | None = None

        try:
            signer_info = api_client.get_signer_status(
                row.docusign_envelope_id,
                role_name=row.template_role_name,
                signer_email=row.signer_email,
            )
        except DocusignApiError:
            return envelope_status, None

        recipient_status = normalize_docusign_status(signer_info.get("status") or "")
        if recipient_status == "completed":
            signed_at = signer_info.get("signed_at")
            return "completed", signed_at
        if recipient_status == "declined":
            return "declined", None
        if (signer_info.get("status") or "").lower() == "delivered":
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
        return normalize_docusign_status(signer_info.get("status") or "") == "completed"

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
        client_id = None
        client_name = None
        client_registered = self._envelope_client_registered(row)
        if client_registered and row.client:
            client_id = row.client_id
            client_name = row.client.full_name
        can_register_client = row.status.lower() == "completed" and not client_registered
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
            client_id=client_id,
            client_name=client_name,
            sent_by_user_id=row.sent_by_user_id,
            sent_by_name=sent_by_name,
            sent_at=row.sent_at,
            completed_at=row.completed_at,
            has_signed_document=bool(row.signed_storage_key),
            can_register_client=can_register_client,
            client_registered=client_registered,
        )

    @staticmethod
    def _resolve_sent_by_user_id(actor: User, client_row: Client | None) -> int:
        """Onboarding/admin envía en nombre del vendedor que registró al cliente."""
        if (
            client_row is not None
            and can_manage_onboarding(actor)
            and client_row.registered_by_user_id
        ):
            return client_row.registered_by_user_id
        return actor.id

    def _envelopes_query(self, actor: User, merchant_id: int, sent_by_user_id: int | None = None):
        query = (
            select(DocusignEnvelope)
            .options(
                joinedload(DocusignEnvelope.client),
                joinedload(DocusignEnvelope.sent_by),
            )
            .where(DocusignEnvelope.merchant_id == merchant_id)
            .order_by(DocusignEnvelope.sent_at.desc())
        )
        if is_sales_staff(actor) or (is_sales_area_leader(actor) and sent_by_user_id is None):
            query = query.where(DocusignEnvelope.sent_by_user_id == actor.id)
        elif sent_by_user_id is not None:
            if not can_supervise_sales_reps(actor):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No autorizado",
                )
            query = query.where(DocusignEnvelope.sent_by_user_id == sent_by_user_id)
        return query

    def list_envelopes(
        self,
        actor: User,
        *,
        merchant_id: int,
        sent_by_user_id: int | None = None,
    ) -> list[DocusignEnvelopeResponse]:
        self.ensure_access(actor)
        if sent_by_user_id is not None and can_supervise_sales_reps(actor):
            self._assert_sales_rep_user(sent_by_user_id)
        rows = self.db.execute(
            self._envelopes_query(actor, merchant_id, sent_by_user_id)
        ).unique().scalars().all()
        return [self._map_envelope(row) for row in rows]

    def _assert_sales_rep_user(self, user_id: int) -> None:
        user = self.db.execute(
            select(User)
            .join(Role)
            .where(User.id == user_id, Role.code.in_(tuple(SALES_STAFF_ROLES)))
        ).scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vendedor no encontrado",
            )

    def list_client_envelopes(
        self,
        actor: User,
        client_id: int,
        *,
        merchant_id: int,
    ) -> list[DocusignEnvelopeResponse]:
        self.ensure_access(actor)
        client_service = ClientService(self.db)
        client = client_service.get_client_for_user(actor, client_id, merchant_id=merchant_id)
        if client is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
        if actor.role.code != "CLIENT" and not client_service.user_can_view_approved_client_workspace(
            actor, client_id, client=client
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

        query = (
            select(DocusignEnvelope)
            .options(
                joinedload(DocusignEnvelope.client),
                joinedload(DocusignEnvelope.sent_by),
            )
            .where(DocusignEnvelope.client_id == client_id)
            .order_by(DocusignEnvelope.sent_at.desc())
        )
        rows = self.db.execute(query).unique().scalars().all()
        return [self._map_envelope(row) for row in rows]

    def _get_envelope_row(self, actor: User, envelope_id: int, *, merchant_id: int | None = None) -> DocusignEnvelope:
        row = self.db.execute(
            select(DocusignEnvelope)
            .options(joinedload(DocusignEnvelope.client), joinedload(DocusignEnvelope.sent_by))
            .where(DocusignEnvelope.id == envelope_id)
        ).unique().scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrato no encontrado")
        if merchant_id is not None and row.merchant_id != merchant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrato no encontrado")
        if is_sales_staff(actor) and row.sent_by_user_id != actor.id:
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

    def _add_notify_user(self, users: list[User], seen: set[int], user: User | None) -> None:
        if user is None or not user.is_active or user.id is None:
            return
        if user.id in seen:
            return
        seen.add(user.id)
        users.append(user)

    def _sales_area_leaders_for_sede(self, sede_id: int | None) -> list[User]:
        if sede_id is None:
            return []
        from app.models.area import Area

        return list(
            self.db.execute(
                select(User)
                .join(Role, User.role_id == Role.id)
                .outerjoin(Area, User.area_id == Area.id)
                .where(
                    User.is_active.is_(True),
                    User.sede_id == sede_id,
                    Role.code == AREA_LEADER_ROLE,
                    Area.code == SALES_AREA_CODE,
                )
            )
            .scalars()
            .all()
        )

    def _completion_recipients(self, locked: DocusignEnvelope, row: DocusignEnvelope) -> list[User]:
        """Quien envió, el dueño del prospecto, su líder y el líder de ventas de la sede."""
        users: list[User] = []
        seen: set[int] = set()

        sent_by = row.sent_by
        if sent_by is None and locked.sent_by_user_id:
            sent_by = self.db.get(User, locked.sent_by_user_id)
        self._add_notify_user(users, seen, sent_by)

        prospect_id = locked.prospect_id
        if prospect_id is not None:
            from app.models.prospect import Prospect

            prospect = self.db.get(Prospect, prospect_id)
            if prospect is not None:
                assigned = prospect.assigned_to
                if assigned is None and prospect.assigned_to_user_id:
                    assigned = self.db.get(User, prospect.assigned_to_user_id)
                self._add_notify_user(users, seen, assigned)
                if assigned is not None and assigned.parent_user_id:
                    self._add_notify_user(users, seen, self.db.get(User, assigned.parent_user_id))
                for leader in self._sales_area_leaders_for_sede(prospect.sede_id):
                    self._add_notify_user(users, seen, leader)

        return users

    def _notify_envelope_completed(self, row: DocusignEnvelope) -> bool:
        """Notifica una sola vez por contrato firmado. Retorna True si creó la notificación."""
        # FOR UPDATE solo sobre docusign_envelopes (PostgreSQL no permite locks con LEFT JOIN).
        locked = self.db.execute(
            select(DocusignEnvelope)
            .where(DocusignEnvelope.id == row.id)
            .with_for_update()
        ).scalar_one_or_none()
        if locked is None:
            return False
        if locked.completion_notified_at is not None:
            row.completion_notified_at = locked.completion_notified_at
            return False

        recipients = self._completion_recipients(locked, row)
        if not recipients:
            return False

        to_notify: list[User] = []
        for user in recipients:
            existing_notification = self.db.execute(
                select(Notification.id).where(
                    Notification.user_id == user.id,
                    Notification.channel == "IN_APP",
                    Notification.event_type == NotificationEventType.DOCUSIGN_ENVELOPE_COMPLETED.value,
                    Notification.payload["envelope_id"].as_integer() == locked.id,
                ).limit(1)
            ).scalar_one_or_none()
            if existing_notification is None:
                to_notify.append(user)

        client = row.client
        if client is None and locked.client_id:
            client = self.db.get(Client, locked.client_id)

        client_label = locked.signer_name
        notify_client_id = None
        if locked.client_id and client and self._client_matches_signer(
            client, locked.signer_name, locked.signer_email
        ):
            client_label = client.full_name
            notify_client_id = locked.client_id

        notified_at = datetime.now(timezone.utc)
        locked.completion_notified_at = notified_at
        row.completion_notified_at = notified_at
        self.db.flush()

        if not to_notify:
            return False

        created = self.notifications.notify(
            event_type=NotificationEventType.DOCUSIGN_ENVELOPE_COMPLETED.value,
            users=to_notify,
            title="Contrato firmado",
            body=f"{client_label} firmó el contrato «{locked.subject}».",
            payload={
                "client_id": notify_client_id,
                "envelope_id": locked.id,
                "prospect_id": locked.prospect_id,
                "signer_name": locked.signer_name,
                "signer_email": locked.signer_email,
            },
            commit=False,
        )
        self._pending_in_app_notifications.extend(created)
        return True

    def _process_completed_envelope(self, row: DocusignEnvelope, *, allow_notify: bool = True) -> bool:
        """Archiva PDF, vincula cliente y notifica (idempotente)."""
        if normalize_docusign_status(row.status) != "completed":
            return False
        if row.status.lower() != "completed":
            row.status = "completed"

        changed = False
        if row.completed_at is None:
            row.completed_at = datetime.now(timezone.utc)
            changed = True
        if self._ensure_client_for_completed_envelope(row):
            changed = True
        if not row.signed_storage_key:
            self._persist_signed_pdf(row)
            if row.signed_storage_key:
                changed = True
        if allow_notify and self._notify_envelope_completed(row):
            changed = True
        if row.prospect_id is not None:
            from app.services.prospects import ProspectService

            ProspectService(self.db).on_envelope_completed(row)
            changed = True
        return changed

    def _apply_remote_status(
        self,
        row: DocusignEnvelope,
        remote: dict,
        *,
        api_client: DocusignClient | None = None,
    ) -> bool:
        if api_client is None:
            api_client = self._client_from_settings()
        previous_status = row.status.lower()
        effective_status, signed_at = self._resolve_effective_status(api_client, row, remote)
        row.status = effective_status
        row.last_status_sync_at = datetime.now(timezone.utc)
        current_status = normalize_docusign_status(row.status)
        if current_status == "completed":
            row.status = "completed"
            row.completed_at = signed_at or row.completed_at or row.last_status_sync_at
        return previous_status != current_status

    def _apply_connect_event(self, row: DocusignEnvelope, event: DocusignConnectEvent) -> bool:
        previous_status = row.status.lower()
        row.status = normalize_docusign_status(event.status)
        row.last_status_sync_at = datetime.now(timezone.utc)
        if row.status.lower() == "completed" and row.completed_at is None:
            row.completed_at = row.last_status_sync_at
        return previous_status != row.status.lower()

    def _commit_docusign_changes(self) -> None:
        from app.services.notifications.hub import notification_hub

        pending_in_app = list(self._pending_in_app_notifications)
        self._pending_in_app_notifications.clear()
        for obj in list(self.db.new):
            if isinstance(obj, Notification) and obj.channel == "IN_APP" and obj.user_id is not None:
                if obj not in pending_in_app:
                    pending_in_app.append(obj)
        self.db.commit()
        for notification in pending_in_app:
            if notification.id is None:
                self.db.refresh(notification)
        if pending_in_app:
            notification_hub.publish_in_app(pending_in_app)

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

        changed = False
        try:
            api_client = self._client_from_settings()
            remote = api_client.get_envelope(row.docusign_envelope_id)
            if self._apply_remote_status(row, remote, api_client=api_client):
                changed = True
        except DocusignApiError:
            logger.warning(
                "DocuSign Connect: no se pudo consultar envelope %s; uso el payload",
                event.envelope_id,
            )
            if self._apply_connect_event(row, event):
                changed = True

        if event.status == "completed" and normalize_docusign_status(row.status) != "declined":
            if row.status.lower() != "completed":
                row.status = "completed"
                if row.completed_at is None:
                    row.completed_at = datetime.now(timezone.utc)
                changed = True

        if row.status.lower() == "completed" and self._process_completed_envelope(row):
            changed = True
        if changed or row.status.lower() == "completed":
            self._commit_docusign_changes()
        return {"received": True, "processed": changed, "envelope_id": event.envelope_id}

    def sync_pending_envelopes(
        self,
        actor: User,
        *,
        merchant_id: int,
        sent_by_user_id: int | None = None,
    ) -> list[DocusignEnvelopeResponse]:
        self.ensure_access(actor)
        if sent_by_user_id is not None and can_supervise_sales_reps(actor):
            self._assert_sales_rep_user(sent_by_user_id)
        query = self._envelopes_query(actor, merchant_id, sent_by_user_id)
        rows = self.db.execute(query).unique().scalars().all()

        api_client = self._client_from_settings()
        changed = False
        for row in rows:
            if row.status.lower() not in DOCUSIGN_TERMINAL_STATUSES:
                try:
                    remote = api_client.get_envelope(row.docusign_envelope_id)
                except DocusignApiError:
                    remote = None
                else:
                    if self._apply_remote_status(row, remote):
                        changed = True
            if normalize_docusign_status(row.status) == "completed" and self._process_completed_envelope(row):
                changed = True

        repaired = 0
        for row in rows:
            if row.status.lower() != "completed":
                continue
            if self._ensure_client_for_completed_envelope(row):
                repaired += 1
                if not row.signed_storage_key:
                    self._persist_signed_pdf(row)

        if changed or repaired:
            self._commit_docusign_changes()
            rows = self.db.execute(query).unique().scalars().all()

        return [self._map_envelope(row) for row in rows]

    def get_sent_document(self, actor: User, envelope_id: int, *, merchant_id: int) -> tuple[bytes, str]:
        row = self._get_envelope_row(actor, envelope_id, merchant_id=merchant_id)
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

    def get_signed_document(self, actor: User, envelope_id: int, *, merchant_id: int) -> tuple[bytes, str]:
        row = self._get_envelope_row(actor, envelope_id, merchant_id=merchant_id)
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
        self,
        actor: User,
        payload: DocusignSendEnvelopeRequest,
        *,
        merchant_id: int,
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
        try:
            role_name = resolve_template_role_name(role_name, valid_roles)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if len(valid_roles) > 1:
            logger.warning(
                "Plantilla %s tiene %s roles (%s); se enviará solo «%s»",
                template_id,
                len(valid_roles),
                ", ".join(valid_roles),
                role_name,
            )

        client_row: Client | None = None
        if payload.client_id is not None:
            client_row = self.db.get(Client, payload.client_id)
            if client_row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
            if client_row.merchant_id != merchant_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
            if can_manage_onboarding(actor):
                client_service = ClientService(self.db)
                if not client_service.user_can_view_approved_client_workspace(
                    actor, payload.client_id, client=client_row
                ):
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
            if not self._client_matches_signer(
                client_row,
                payload.signer_name,
                str(payload.signer_email),
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El cliente seleccionado no coincide con el nombre y email del firmante",
                )

        resolved_client_id = payload.client_id
        prospect_row = None
        if payload.prospect_id is not None:
            from app.models.prospect import Prospect
            from app.services.prospects import ProspectService

            prospect_service = ProspectService(self.db)
            prospect_row = prospect_service._get_prospect_for_user(actor, payload.prospect_id, merchant_id=merchant_id)
            if not (
                prospect_row.email.lower() == str(payload.signer_email).strip().lower()
                and prospect_row.first_name.lower() in payload.signer_name.lower()
            ):
                # Relaxed match: email must match
                if prospect_row.email.lower() != str(payload.signer_email).strip().lower():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="El prospecto no coincide con el email del firmante",
                    )

        sent_by_user_id = self._resolve_sent_by_user_id(actor, client_row)

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
            sent_by_user_id=sent_by_user_id,
            merchant_id=client_row.merchant_id if client_row is not None else merchant_id,
            client_id=resolved_client_id,
            prospect_id=payload.prospect_id,
            signer_name=payload.signer_name.strip(),
            signer_email=str(payload.signer_email).strip().lower(),
            template_id=template_id,
            template_role_name=role_name,
            subject=payload.subject.strip(),
            status=result.get("status") or "sent",
            sent_at=datetime.now(timezone.utc),
        )
        self.db.add(row)
        self.db.flush()
        if prospect_row is not None:
            from app.services.prospects import ProspectService

            ProspectService(self.db).attach_envelope(actor=actor, prospect=prospect_row, envelope=row)
        self.db.commit()
        self.db.refresh(row)
        row = self.db.execute(
            select(DocusignEnvelope)
            .options(joinedload(DocusignEnvelope.client), joinedload(DocusignEnvelope.sent_by))
            .where(DocusignEnvelope.id == row.id)
        ).unique().scalar_one()

        return DocusignSendEnvelopeResponse(envelope=self._map_envelope(row))

    def sync_envelope_status(
        self,
        actor: User,
        envelope_id: int,
        *,
        merchant_id: int,
    ) -> DocusignEnvelopeResponse:
        self.ensure_access(actor)
        row = self._get_envelope_row(actor, envelope_id, merchant_id=merchant_id)

        api_client = self._client_from_settings()
        try:
            remote = api_client.get_envelope(row.docusign_envelope_id)
        except DocusignApiError as exc:
            raise self._docusign_http_error(exc) from exc

        self._apply_remote_status(row, remote)
        if normalize_docusign_status(row.status) == "completed":
            self._process_completed_envelope(row)
        self._commit_docusign_changes()
        self.db.refresh(row)
        return self._map_envelope(row)
