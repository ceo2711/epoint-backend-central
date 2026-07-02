"""Cliente HTTP para DocuSign eSignature REST API (JWT Grant)."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import httpx
from jose import jwt

DOCUSIGN_SCOPES = "signature impersonation"
JWT_LIFETIME_SECONDS = 3600


class DocusignApiError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DocusignClient:
    def __init__(
        self,
        *,
        integration_key: str,
        impersonated_user_id: str,
        account_id: str,
        private_key_pem: str,
        base_uri: str,
        auth_server: str = "account-d.docusign.com",
    ) -> None:
        self.integration_key = integration_key.strip()
        self.impersonated_user_id = impersonated_user_id.strip()
        self.account_id = account_id.strip()
        self.private_key_pem = private_key_pem.strip()
        self.base_uri = base_uri.rstrip("/")
        self.auth_server = auth_server.strip()
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    @staticmethod
    def consent_url(*, integration_key: str, auth_server: str, redirect_uri: str) -> str:
        scope = quote(DOCUSIGN_SCOPES)
        redirect = quote(redirect_uri, safe="")
        return (
            f"https://{auth_server}/oauth/auth"
            f"?response_type=code&scope={scope}"
            f"&client_id={integration_key}"
            f"&redirect_uri={redirect}"
        )

    def _build_jwt_assertion(self) -> str:
        now = int(time.time())
        claims = {
            "iss": self.integration_key,
            "sub": self.impersonated_user_id,
            "aud": self.auth_server,
            "iat": now,
            "exp": now + JWT_LIFETIME_SECONDS,
            "scope": DOCUSIGN_SCOPES,
        }
        return jwt.encode(claims, self.private_key_pem, algorithm="RS256")

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        if (
            not force_refresh
            and self._access_token
            and time.time() < self._token_expires_at - 60
        ):
            return self._access_token

        assertion = self._build_jwt_assertion()
        url = f"https://{self.auth_server}/oauth/token"
        try:
            response = httpx.post(
                url,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise DocusignApiError(f"No se pudo conectar con DocuSign: {exc}") from exc

        if response.status_code == 400:
            detail = response.text[:500]
            if "consent_required" in detail.lower():
                raise DocusignApiError(
                    "DocuSign requiere consentimiento del usuario impersonado. "
                    "Usá GET /docusign/consent-url y abrí el enlace como admin de DocuSign.",
                    status_code=400,
                )
            raise DocusignApiError(f"Error de autenticación DocuSign: {detail}", status_code=400)

        if response.status_code >= 400:
            raise DocusignApiError(
                f"DocuSign OAuth respondió {response.status_code}: {response.text[:300]}",
                status_code=response.status_code,
            )

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise DocusignApiError("DocuSign no devolvió access_token")
        expires_in = int(payload.get("expires_in") or JWT_LIFETIME_SECONDS)
        self._access_token = token
        self._token_expires_at = time.time() + expires_in
        return token

    @classmethod
    def resolve_account_from_userinfo(
        cls,
        *,
        integration_key: str,
        impersonated_user_id: str,
        private_key_pem: str,
        auth_server: str,
        account_id: str | None = None,
    ) -> dict[str, str]:
        """Obtiene base_uri y valida credenciales vía userinfo."""
        temp = cls(
            integration_key=integration_key,
            impersonated_user_id=impersonated_user_id,
            account_id=account_id or "pending",
            private_key_pem=private_key_pem,
            base_uri="https://demo.docusign.net/restapi",
            auth_server=auth_server,
        )
        token = temp.get_access_token(force_refresh=True)
        try:
            response = httpx.get(
                f"https://{auth_server}/oauth/userinfo",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise DocusignApiError(f"No se pudo obtener userinfo: {exc}") from exc

        if response.status_code >= 400:
            raise DocusignApiError(
                f"Userinfo DocuSign falló ({response.status_code}): {response.text[:300]}",
                status_code=response.status_code,
            )

        data = response.json()
        accounts = data.get("accounts") or []
        if not accounts:
            raise DocusignApiError("La cuenta DocuSign no tiene accounts asociados")

        selected = None
        if account_id:
            for account in accounts:
                if account.get("account_id") == account_id:
                    selected = account
                    break
            if selected is None:
                raise DocusignApiError(f"Account ID {account_id} no encontrado en DocuSign")
        else:
            selected = accounts[0]

        base_uri = selected.get("base_uri", "").rstrip("/") + "/restapi"
        return {
            "account_id": selected["account_id"],
            "account_name": selected.get("account_name") or "",
            "base_uri": base_uri,
            "impersonated_user_email": data.get("email") or "",
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.get_access_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_uri}{path}"
        try:
            response = httpx.request(
                method,
                url,
                headers=self._headers(),
                params=params,
                json=json_body,
                timeout=45.0,
            )
        except httpx.HTTPError as exc:
            raise DocusignApiError(f"Error de red con DocuSign: {exc}") from exc

        if response.status_code == 401:
            self.get_access_token(force_refresh=True)
            response = httpx.request(
                method,
                url,
                headers=self._headers(),
                params=params,
                json=json_body,
                timeout=45.0,
            )

        if response.status_code >= 400:
            raise DocusignApiError(
                f"DocuSign API {response.status_code}: {response.text[:400]}",
                status_code=response.status_code,
            )

        if not response.content:
            return {}
        return response.json()

    def list_templates(self, *, count: int = 50) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            f"/v2.1/accounts/{self.account_id}/templates",
            params={"count": str(count)},
        )
        return payload.get("envelopeTemplates") or []

    def get_template(self, template_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v2.1/accounts/{self.account_id}/templates/{template_id}",
        )

    def create_envelope_from_template(
        self,
        *,
        template_id: str,
        role_name: str,
        signer_name: str,
        signer_email: str,
        subject: str,
        text_tabs: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        role: dict[str, Any] = {
            "roleName": role_name,
            "name": signer_name.strip(),
            "email": signer_email.strip().lower(),
        }
        if text_tabs:
            role["tabs"] = {
                "textTabs": [
                    {"tabLabel": label, "value": value}
                    for label, value in text_tabs.items()
                    if value.strip()
                ]
            }

        body = {
            "templateId": template_id,
            "templateRoles": [role],
            "status": "sent",
            "emailSubject": subject.strip(),
        }
        return self._request(
            "POST",
            f"/v2.1/accounts/{self.account_id}/envelopes",
            json_body=body,
        )

    def get_envelope(self, envelope_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v2.1/accounts/{self.account_id}/envelopes/{envelope_id}",
        )

    def download_combined_document(self, envelope_id: str) -> bytes:
        url = (
            f"{self.base_uri}/v2.1/accounts/{self.account_id}"
            f"/envelopes/{envelope_id}/documents/combined"
        )
        try:
            response = httpx.get(
                url,
                headers={
                    **self._headers(),
                    "Accept": "application/pdf",
                },
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            raise DocusignApiError(f"Error de red con DocuSign: {exc}") from exc

        if response.status_code == 401:
            self.get_access_token(force_refresh=True)
            response = httpx.get(
                url,
                headers={
                    **self._headers(),
                    "Accept": "application/pdf",
                },
                timeout=60.0,
            )

        if response.status_code >= 400:
            raise DocusignApiError(
                f"DocuSign API {response.status_code}: {response.text[:400]}",
                status_code=response.status_code,
            )

        return response.content
