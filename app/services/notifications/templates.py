"""Plantillas de mensajes para notificaciones transaccionales.

El email de bienvenida al aprobar un cliente se envía vía
`app.services.email.send_client_welcome_email` (no por NotificationService).

El WhatsApp de bienvenida se envía vía
`app.services.whatsapp.send_client_welcome_whatsapp` (no por NotificationService).
"""


def client_approved_in_app_body(*, first_name: str) -> str:
    return (
        f"Hola {first_name}, tu cuenta fue aprobada. "
        "Revisá tu correo y WhatsApp: allí están tus credenciales para ingresar al portal "
        "y cargar tus datos y documentos."
    )


def client_approved_email_body(
    *,
    first_name: str,
    email: str,
    temp_password: str,
    portal_login_url: str,
    merchant_name: str | None = None,
) -> str:
    merchant_block = ""
    if merchant_name:
        merchant_block = f"\nTu cuenta corresponde a {merchant_name}.\n"
    return f"""Hola {first_name},
{merchant_block}
¡Bienvenido/a a ePoint!

Tu solicitud fue aprobada. Ya podés ingresar al portal del cliente para completar tus datos personales y subir la documentación requerida.

Credenciales de acceso
──────────────────────
Portal: {portal_login_url}
Usuario (email): {email}
Contraseña temporal: {temp_password}

En tu primer ingreso deberás cambiar la contraseña temporal.

Si tenés alguna consulta, respondé a este correo o contactá a tu asesor ePoint.

Saludos,
Equipo ePoint
"""


def client_approved_whatsapp_body(
    *,
    first_name: str,
    email: str,
    temp_password: str,
    portal_login_url: str,
) -> str:
    return (
        f"Hola {first_name}, ¡bienvenido/a a ePoint! Tu cuenta fue aprobada.\n\n"
        f"Ingresá al portal para cargar tus datos y documentos:\n"
        f"{portal_login_url}\n\n"
        f"Usuario: {email}\n"
        f"Contraseña temporal: {temp_password}\n\n"
        "En el primer ingreso deberás cambiar la contraseña."
    )


def client_approved_whatsapp_content_variables(
    *,
    first_name: str,
    email: str,
    temp_password: str,
    portal_login_url: str,
) -> dict[str, str]:
    """Variables para plantilla Twilio Content ({{1}}..{{4}})."""
    return {
        "1": first_name,
        "2": portal_login_url,
        "3": email,
        "4": temp_password,
    }


def onboarding_reminder_email_body(
    *,
    first_name: str,
    pending_items: list[str],
    portal_login_url: str,
    locale: str = "es",
) -> str:
    items_block = "\n".join(f"  • {item}" for item in pending_items)
    if locale.lower().startswith("en"):
        return f"""Hi {first_name},

We're writing from ePoint to remind you that you still have pending items to complete your onboarding.

To continue, sign in to the portal and complete the following:

{items_block}

Client portal: {portal_login_url}

If you already uploaded a document, it may be under review. If it was rejected, please upload it again from the documents section.

If you have any questions, reply to this email or contact your ePoint advisor.

Best regards,
ePoint Team
"""
    return f"""Hola {first_name},

Te escribimos desde ePoint para recordarte amablemente que aún tenés pendiente completar tu onboarding en la plataforma.

Para continuar con tu proceso, ingresá al portal y completá lo siguiente:

{items_block}

Portal del cliente: {portal_login_url}

Si ya subiste algún documento, puede estar en revisión. Si fue rechazado, volvé a subirlo desde la sección de documentos.

Ante cualquier duda, respondé a este correo o contactá a tu asesor ePoint.

Saludos,
Equipo ePoint
"""


def onboarding_reminder_whatsapp_body(
    *,
    first_name: str,
    pending_items: list[str],
    portal_login_url: str,
    locale: str = "es",
) -> str:
    items_block = "\n".join(f"• {item}" for item in pending_items)
    if locale.lower().startswith("en"):
        return (
            f"Hi {first_name}, this is a reminder from ePoint that you still have pending onboarding items.\n\n"
            f"Pending:\n{items_block}\n\n"
            f"Sign in to the portal:\n{portal_login_url}\n\n"
            "If a document was rejected, please upload it again from the platform."
        )
    return (
        f"Hola {first_name}, te recordamos desde ePoint que aún tenés pendiente completar tu onboarding.\n\n"
        f"Pendiente:\n{items_block}\n\n"
        f"Ingresá al portal:\n{portal_login_url}\n\n"
        "Si algún documento fue rechazado, volvé a subirlo desde la plataforma."
    )


def password_reset_email_body(
    *,
    first_name: str,
    reset_url: str,
    expire_minutes: int,
) -> str:
    return f"""Hola {first_name},

Recibimos una solicitud para restablecer la contraseña de tu cuenta en ePoint.

Para elegir una nueva contraseña, abrí el siguiente enlace (válido por {expire_minutes} minutos):

{reset_url}

Si no solicitaste este cambio, ignorá este correo. Tu contraseña actual seguirá siendo la misma.

Saludos,
Equipo ePoint
"""
