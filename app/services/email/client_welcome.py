"""Correo de bienvenida al aprobar un cliente (credenciales del portal)."""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClientWelcomeEmailPayload:
    recipient_email: str
    first_name: str
    temp_password: str
    portal_login_url: str
    client_id: int | None = None


def send_client_welcome_email(payload: ClientWelcomeEmailPayload) -> bool:
    """Envía el email de bienvenida con credenciales del portal.

    Punto único de envío: lo invoca `ClientService.approve_client` y el script
    `scripts/send_client_welcome_email.py` para reenvíos manuales.
    """
    # TODO: implementar envío real (SendGrid, SMTP, plantilla HTML, etc.)
    logger.info(
        "send_client_welcome_email: pendiente de implementación → %s (cliente_id=%s)",
        payload.recipient_email,
        payload.client_id,
    )
    return True
