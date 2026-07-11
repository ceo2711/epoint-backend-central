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
