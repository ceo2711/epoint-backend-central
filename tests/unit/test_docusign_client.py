from unittest.mock import patch

import pytest

from app.services.docusign.client import DocusignClient


def test_consent_url_format():
    url = DocusignClient.consent_url(
        integration_key="abc-123",
        auth_server="account-d.docusign.com",
        redirect_uri="http://localhost:3000/contratos",
    )
    assert "account-d.docusign.com/oauth/auth" in url
    assert "client_id=abc-123" in url
    assert "signature" in url


def test_jwt_assertion_builds():
    client = DocusignClient(
        integration_key="integration-key",
        impersonated_user_id="user-guid",
        account_id="account-guid",
        private_key_pem="-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAK\n-----END RSA PRIVATE KEY-----",
        base_uri="https://demo.docusign.net/restapi",
        auth_server="account-d.docusign.com",
    )
    with patch("app.services.docusign.client.jwt.encode", return_value="signed-jwt") as mock_encode:
        token = client._build_jwt_assertion()
    assert token == "signed-jwt"
    mock_encode.assert_called_once()
    claims = mock_encode.call_args[0][0]
    assert claims["iss"] == "integration-key"
    assert claims["sub"] == "user-guid"
    assert claims["aud"] == "account-d.docusign.com"
