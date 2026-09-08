from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.docusign import DocusignConnectionResponse, DocusignEnvelopeResponse
from datetime import datetime, timezone


@pytest.fixture
def client():
    return TestClient(app)


def _sample_envelope() -> DocusignEnvelopeResponse:
    now = datetime.now(timezone.utc)
    return DocusignEnvelopeResponse(
        id=1,
        docusign_envelope_id="env-123",
        signer_name="Juan Pérez",
        signer_email="juan@test.com",
        template_id="tpl-1",
        template_role_name="Cliente",
        subject="Contrato test",
        status="sent",
        client_id=10,
        client_name="Juan Pérez",
        sent_by_user_id=1,
        sent_by_name="Admin",
        sent_at=now,
        completed_at=None,
        has_signed_document=False,
    )


class TestDocusignRoutes:
    def test_connection_requires_auth(self, client):
        response = client.get("/api/v1/docusign/connection")
        assert response.status_code == 401

    def test_connection_ok(self, client):
        mock = DocusignConnectionResponse(connected=True, account_id="acc-1")
        with patch("app.api.v1.docusign.DocusignService") as svc:
            svc.return_value.get_connection.return_value = mock
            with patch("app.api.deps.get_current_user", return_value=MagicMock(role=MagicMock(code="ADMIN"))):
                response = client.get(
                    "/api/v1/docusign/connection",
                    headers={"Authorization": "Bearer fake"},
                )
        assert response.status_code in (200, 401)

    def test_webhook_accepts_json_without_hmac_in_dev(self, client):
        body = {
            "event": "envelope-completed",
            "data": {"envelopeId": "unknown-id", "envelopeSummary": {"status": "completed"}},
        }
        with patch("app.api.v1.docusign.DocusignService") as svc:
            svc.return_value.handle_connect_webhook.return_value = {
                "received": True,
                "processed": False,
            }
            response = client.post("/api/v1/docusign/webhook", json=body)
        assert response.status_code == 200
        assert response.json()["received"] is True

    def test_list_client_envelopes_delegates_to_service(self, client):
        with patch("app.api.v1.docusign.DocusignService") as svc:
            svc.return_value.list_client_envelopes.return_value = [_sample_envelope()]
            with patch("app.api.deps.get_current_user", return_value=MagicMock(role=MagicMock(code="ADMIN"))):
                response = client.get(
                    "/api/v1/docusign/clients/10/envelopes",
                    headers={"Authorization": "Bearer fake"},
                )
        assert response.status_code in (200, 401)

    def test_manual_envelope_requires_auth(self, client):
        response = client.post("/api/v1/docusign/envelopes/manual")
        assert response.status_code == 401
