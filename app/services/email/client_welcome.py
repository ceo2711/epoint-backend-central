"""Correo de bienvenida al aprobar un cliente (credenciales del portal)."""

from dataclasses import dataclass

from app.core.config import get_settings
from app.services.email.html_templates import (
    branding_asset_url_for_emails,
    logo_url_for_emails,
    render_html_template,
    store_link_href,
)
from app.services.email.resend_delivery import send_resend_text_email
from app.services.notifications.templates import client_approved_email_body

WELCOME_EMAIL_SUBJECT = "¡Bienvenido a Epoint!"


@dataclass(frozen=True, slots=True)
class ClientWelcomeEmailPayload:
    recipient_email: str
    first_name: str
    temp_password: str
    portal_login_url: str
    client_id: int | None = None
    merchant_name: str | None = None


def send_client_welcome_email(payload: ClientWelcomeEmailPayload) -> bool:
    """Envía el email de bienvenida con credenciales del portal vía Resend."""
    recipient = payload.recipient_email.strip().lower()
    settings = get_settings()
    android_href = store_link_href(settings.android_app_store_url)
    ios_href = store_link_href(settings.ios_app_store_url)
    text_body = client_approved_email_body(
        first_name=payload.first_name,
        email=recipient,
        temp_password=payload.temp_password,
        portal_login_url=payload.portal_login_url,
        merchant_name=payload.merchant_name,
        android_app_store_url=android_href if android_href != "#" else "",
        ios_app_store_url=ios_href if ios_href != "#" else "",
    )
    html_body = render_html_template(
        "welcome",
        FIRST_NAME=payload.first_name,
        EMAIL=recipient,
        TEMP_PASSWORD=payload.temp_password,
        PORTAL_LOGIN_URL=payload.portal_login_url,
        LOGO_URL=logo_url_for_emails(settings),
        MERCHANT_LINE=(
            f"Tu cuenta corresponde a {payload.merchant_name}."
            if payload.merchant_name
            else ""
        ),
        ANDROID_APP_STORE_URL=android_href,
        IOS_APP_STORE_URL=ios_href,
        GOOGLE_PLAY_BADGE_URL=branding_asset_url_for_emails(settings, "google-play-badge"),
        APP_STORE_BADGE_URL=branding_asset_url_for_emails(settings, "app-store-badge"),
    )
    return send_resend_text_email(
        intended_recipient=recipient,
        subject=WELCOME_EMAIL_SUBJECT,
        text=text_body,
        html=html_body,
        log_context=f"welcome cliente_id={payload.client_id}" if payload.client_id else "welcome",
    )
