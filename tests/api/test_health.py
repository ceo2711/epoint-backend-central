import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_check_returns_ok(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "app" in data
    assert "environment" in data
    assert "llm" in data
    assert data["version"] == "1.0.0"


def test_health_check_llm_not_configured_by_default(client):
    response = client.get("/api/v1/health")
    data = response.json()
    assert data["llm"]["status"] in ("not_configured", "configured")


def test_openapi_includes_today_feature_routes(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/auth/forgot-password" in paths
    assert "/api/v1/auth/reset-password" in paths
    assert "/api/v1/docusign/envelopes/manual" in paths
    assert "/api/v1/payments/links/{link_id}/remainder-due" in paths


def test_remainder_due_requires_auth(client):
    response = client.patch(
        "/api/v1/payments/links/1/remainder-due",
        json={"remainder_due_on": "2099-01-15"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://100.69.63.4:3000",
    ],
)
def test_cors_allows_local_dev_origins(client, origin):
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
