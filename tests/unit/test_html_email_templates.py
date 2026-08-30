import pytest

from app.services.email.html_templates import (
    EmailTemplateError,
    logo_url_for_emails,
    pending_items_html,
    render_html_template,
    resolve_email_logo_url,
)


def test_render_welcome_template_substitutes_placeholders():
    html = render_html_template(
        "welcome",
        FIRST_NAME="Ana",
        EMAIL="ana@example.com",
        TEMP_PASSWORD="secret123",
        PORTAL_LOGIN_URL="https://app.example.com/login",
        LOGO_URL="https://app.example.com/epoint-logo.png",
        ANDROID_APP_STORE_URL="#",
        IOS_APP_STORE_URL="#",
        GOOGLE_PLAY_BADGE_URL="https://app.example.com/google-play-badge.png",
        APP_STORE_BADGE_URL="https://app.example.com/app-store-badge.png",
    )
    assert "Ana" in html
    assert "ana@example.com" in html
    assert "secret123" in html
    assert "https://app.example.com/login" in html
    assert "epoint-logo.png" in html
    assert "google-play-badge.png" in html
    assert "app-store-badge.png" in html
    assert "Disponible en Google Play" in html
    assert "Download on the App Store" in html
    assert "{{FIRST_NAME}}" not in html
    assert "{{GOOGLE_PLAY_BADGE_URL}}" not in html


def test_render_payment_link_template_substitutes_placeholders():
    html = render_html_template(
        "payment_link",
        FIRST_NAME="Juan",
        AMOUNT_FORMATTED="USD 99.00",
        PAYMENT_URL="https://app.example.com/pagar/token123",
        PROVIDER_LABEL="PayPal",
        LOGO_URL="https://app.example.com/epoint-logo.png",
        MERCHANT_LINE="Tu pago corresponde a Acme Corp.",
        DESCRIPTION_BLOCK='<p><strong>Concepto:</strong> Consultoría</p>',
    )
    assert "Juan" in html
    assert "USD 99.00" in html
    assert "https://app.example.com/pagar/token123" in html
    assert "PayPal" in html
    assert "Completar pago" in html
    assert "{{PAYMENT_URL}}" not in html
    assert "soporte técnico" in html
    assert "https://epointsolution.com/" in html


def test_render_client_conversion_welcome_template_substitutes_placeholders():
    html = render_html_template(
        "client_conversion_welcome",
        FIRST_NAME="Juan",
        AMOUNT_FORMATTED="USD 99.00",
        LOGO_URL="https://app.example.com/epoint-logo.png",
        MERCHANT_LINE="Tu proceso corresponde a Acme Corp.",
    )
    assert "Juan" in html
    assert "USD 99.00" in html
    assert "Acme Corp." in html
    assert "Pago confirmado" in html
    assert "{{AMOUNT_FORMATTED}}" not in html


def test_pending_items_html_escapes_special_chars():
    html = pending_items_html(['Item <script> & "test"'])
    assert "&lt;script&gt;" in html
    assert "&amp;" in html
    assert "<script>" not in html


def test_logo_url_for_emails_prefers_backend_public_endpoint():
    assert (
        resolve_email_logo_url(
            email_logo_url="",
            backend_public_url="https://api.example.com",
            api_prefix="/api/v1",
            portal_base_url="http://localhost:3000",
        )
        == "https://api.example.com/api/v1/branding/logo"
    )


def test_logo_url_for_emails_honors_explicit_override():
    assert (
        resolve_email_logo_url(
            email_logo_url="https://cdn.example.com/logo.png",
            backend_public_url="https://api.example.com",
            api_prefix="/api/v1",
            portal_base_url="http://localhost:3000",
        )
        == "https://cdn.example.com/logo.png"
    )


def test_logo_url_for_emails_falls_back_to_frontend_asset():
    assert (
        resolve_email_logo_url(
            email_logo_url="",
            backend_public_url="",
            api_prefix="/api/v1",
            portal_base_url="https://app.example.com",
        )
        == "https://app.example.com/epoint-logo.png"
    )


def test_missing_template_raises():
    with pytest.raises(EmailTemplateError):
        render_html_template("nonexistent_template_xyz")
