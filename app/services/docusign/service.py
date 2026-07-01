"""Integración DocuSign — conexión empresa y envío de contratos."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.encryption import decrypt_value, encrypt_value
from app.models.client import Client
from app.models.docusign_connection import DocusignConnection
from app.models.docusign_envelope import DocusignEnvelope
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.docusign import (
    DocusignConnectRequest,
    DocusignConnectionResponse,
    DocusignConsentUrlResponse,
    DocusignEnvelopeResponse,
    DocusignSendEnvelopeRequest,
    DocusignSendEnvelopeResponse,
    DocusignTemplateDetailResponse,
    DocusignTemplateResponse,
    DocusignTemplateRoleResponse,
)
from app.services.docusign.client import DocusignApiError, DocusignClient

DOCUSIGN_ROLES = frozenset({"ADMIN", "SALES_REP"})


class DocusignService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    @staticmethod
    def ensure_access(actor: User) -> None:
        if actor.role.code not in DOCUSIGN_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene acceso a contratos DocuSign",
            )

    @staticmethod
    def ensure_admin(actor: User) -> None:
        if actor.role.code != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo administradores pueden configurar DocuSign",
            )

    def _get_connection_row(self) -> DocusignConnection | None:
        return self.db.execute(select(DocusignConnection).limit(1)).scalar_one_or_none()

    def _client_from_connection(self, connection: DocusignConnection) -> DocusignClient:
        private_key = decrypt_value(connection.private_key_encrypted)
        return DocusignClient(
            integration_key=connection.integration_key,
            impersonated_user_id=connection.impersonated_user_id,
            account_id=connection.account_id,
            private_key_pem=private_key,
            base_uri=connection.base_uri,
            auth_server=connection.auth_server,
        )

    def _require_client(self) -> tuple[DocusignClient, DocusignConnection]:
        connection = self._get_connection_row()
        if connection is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="DocuSign no está conectado. Un administrador debe vincular la cuenta.",
            )
        return self._client_from_connection(connection), connection

    @staticmethod
    def _map_connection(connection: DocusignConnection | None) -> DocusignConnectionResponse:
        if connection is None:
            return DocusignConnectionResponse(connected=False)
        return DocusignConnectionResponse(
            connected=True,
            account_id=connection.account_id,
            account_name=connection.account_name,
            impersonated_user_email=connection.impersonated_user_email,
            auth_server=connection.auth_server,
            default_template_id=connection.default_template_id,
            default_template_role_name=connection.default_template_role_name,
            connected_at=connection.connected_at,
        )

    def get_connection(self, actor: User) -> DocusignConnectionResponse:
        self.ensure_access(actor)
        return self._map_connection(self._get_connection_row())

    def get_consent_url(self, actor: User) -> DocusignConsentUrlResponse:
        self.ensure_admin(actor)
        connection = self._get_connection_row()
        if connection is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Conectá DocuSign primero para generar el enlace de consentimiento",
            )
        redirect_uri = f"{self.settings.portal_base_url}/contratos"
        consent_url = DocusignClient.consent_url(
            integration_key=connection.integration_key,
            auth_server=connection.auth_server,
            redirect_uri=redirect_uri,
        )
        return DocusignConsentUrlResponse(consent_url=consent_url, redirect_uri=redirect_uri)

    def connect(self, actor: User, payload: DocusignConnectRequest) -> DocusignConnectionResponse:
        self.ensure_admin(actor)
        if not self.settings.encryption_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ENCRYPTION_KEY no configurada — no se pueden guardar credenciales",
            )

        try:
            account_info = DocusignClient.resolve_account_from_userinfo(
                integration_key=payload.integration_key.strip(),
                impersonated_user_id=payload.impersonated_user_id.strip(),
                private_key_pem=payload.private_key.strip(),
                auth_server=payload.auth_server.strip(),
                account_id=payload.account_id.strip(),
            )
        except DocusignApiError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        encrypted_key = encrypt_value(payload.private_key.strip())
        existing = self._get_connection_row()
        if existing is None:
            connection = DocusignConnection(
                integration_key=payload.integration_key.strip(),
                account_id=account_info["account_id"],
                impersonated_user_id=payload.impersonated_user_id.strip(),
                impersonated_user_email=account_info.get("impersonated_user_email"),
                account_name=account_info.get("account_name"),
                base_uri=account_info["base_uri"],
                auth_server=payload.auth_server.strip(),
                private_key_encrypted=encrypted_key,
                default_template_id=payload.default_template_id,
                default_template_role_name=payload.default_template_role_name.strip() or "Signer",
                connected_by_user_id=actor.id,
            )
            self.db.add(connection)
        else:
            connection = existing
            connection.integration_key = payload.integration_key.strip()
            connection.account_id = account_info["account_id"]
            connection.impersonated_user_id = payload.impersonated_user_id.strip()
            connection.impersonated_user_email = account_info.get("impersonated_user_email")
            connection.account_name = account_info.get("account_name")
            connection.base_uri = account_info["base_uri"]
            connection.auth_server = payload.auth_server.strip()
            connection.private_key_encrypted = encrypted_key
            connection.default_template_id = payload.default_template_id
            connection.default_template_role_name = (
                payload.default_template_role_name.strip() or "Signer"
            )
            connection.connected_by_user_id = actor.id

        self.db.commit()
        self.db.refresh(connection)
        return self._map_connection(connection)

    def disconnect(self, actor: User) -> MessageResponse:
        self.ensure_admin(actor)
        connection = self._get_connection_row()
        if connection is None:
            return MessageResponse(message="DocuSign ya estaba desconectado")
        self.db.delete(connection)
        self.db.commit()
        return MessageResponse(message="DocuSign desconectado")

    def list_templates(self, actor: User) -> list[DocusignTemplateResponse]:
        self.ensure_access(actor)
        client, _ = self._require_client()
        try:
            templates = client.list_templates()
        except DocusignApiError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

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
        client, _ = self._require_client()
        try:
            detail = client.get_template(template_id)
        except DocusignApiError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

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
        )

    def list_envelopes(self, actor: User) -> list[DocusignEnvelopeResponse]:
        self.ensure_access(actor)
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

        rows = self.db.execute(query).unique().scalars().all()
        return [self._map_envelope(row) for row in rows]

    def send_envelope(
        self, actor: User, payload: DocusignSendEnvelopeRequest
    ) -> DocusignSendEnvelopeResponse:
        self.ensure_access(actor)
        client, connection = self._require_client()

        template_id = payload.template_id or connection.default_template_id
        role_name = payload.template_role_name or connection.default_template_role_name
        if not template_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Seleccioná una plantilla o configurá una plantilla por defecto",
            )

        client_row: Client | None = None
        if payload.client_id is not None:
            client_row = self.db.get(Client, payload.client_id)
            if client_row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")

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
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        envelope_id = result.get("envelopeId")
        if not envelope_id:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="DocuSign no devolvió envelopeId",
            )

        row = DocusignEnvelope(
            docusign_envelope_id=envelope_id,
            sent_by_user_id=actor.id,
            client_id=payload.client_id,
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
        row = self.db.execute(
            select(DocusignEnvelope)
            .options(joinedload(DocusignEnvelope.client), joinedload(DocusignEnvelope.sent_by))
            .where(DocusignEnvelope.id == envelope_id)
        ).unique().scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrato no encontrado")
        if actor.role.code == "SALES_REP" and row.sent_by_user_id != actor.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puede sincronizar este contrato")

        api_client, _ = self._require_client()
        try:
            remote = api_client.get_envelope(row.docusign_envelope_id)
        except DocusignApiError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        row.status = remote.get("status") or row.status
        row.last_status_sync_at = datetime.now(timezone.utc)
        if row.status.lower() == "completed" and row.completed_at is None:
            row.completed_at = row.last_status_sync_at
        self.db.commit()
        self.db.refresh(row)
        return self._map_envelope(row)
