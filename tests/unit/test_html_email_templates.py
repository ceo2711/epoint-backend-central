import pytest

from app.services.email.html_templates import (
    EmailTemplateError,
    logo_url_for_emails,
    pending_items_html,
    render_html_template,
)


def test_render_welcome_template_substitutes_placeholders():
    html = render_html_template(
        "welcome",
        FIRST_NAME="Ana",
        EMAIL="ana@example.com",
        TEMP_PASSWORD="secret123",
        PORTAL_LOGIN_URL="https://app.example.com/login",
        LOGO_URL="https://app.example.com/epoint-logo.png",
    )
    assert "Ana" in html
    assert "ana@example.com" in html
    assert "secret123" in html
    assert "https://app.example.com/login" in html
    assert "epoint-logo.png" in html
    assert "{{FIRST_NAME}}" not in html


def test_pending_items_html_escapes_special_chars():
    html = pending_items_html(['Item <script> & "test"'])
    assert "&lt;script&gt;" in html
    assert "&amp;" in html
    assert "<script>" not in html


def test_logo_url_for_emails():
    assert logo_url_for_emails("https://app.example.com/") == "https://app.example.com/epoint-logo.png"


def test_missing_template_raises():
    with pytest.raises(EmailTemplateError):
        render_html_template("nonexistent_template_xyz")
