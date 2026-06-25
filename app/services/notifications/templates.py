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
) -> str:
    return f"""Hola {first_name},

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
) -> str:
    items_block = "\n".join(f"  • {item}" for item in pending_items)
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
) -> str:
    items_block = "\n".join(f"• {item}" for item in pending_items)
    return (
        f"Hola {first_name}, te recordamos desde ePoint que aún tenés pendiente completar tu onboarding.\n\n"
        f"Pendiente:\n{items_block}\n\n"
        f"Ingresá al portal:\n{portal_login_url}\n\n"
        "Si algún documento fue rechazado, volvé a subirlo desde la plataforma."
    )

