import pytest
from fastapi.testclient import TestClient

from app.main import app

ASSET_PATHS = [
    "/api/v1/branding/logo",
    "/api/v1/branding/google-play-badge",
    "/api/v1/branding/app-store-badge",
]


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.parametrize("path", ASSET_PATHS)
def test_branding_asset_is_served_as_png(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 0


@pytest.mark.parametrize("path", ASSET_PATHS)
def test_branding_asset_is_inline_for_email_clients(client, path):
    """Con "attachment" los clientes de email no renderizan el <img>."""
    response = client.get(path)
    assert response.headers["content-disposition"].startswith("inline")
