"""Plantillas de mensajes para notificaciones transaccionales.

El email de bienvenida al aprobar un cliente se envía vía
`app.services.email.send_client_welcome_email` (no por NotificationService).

El WhatsApp de bienvenida se envía vía
`app.services.whatsapp.send_client_welcome_whatsapp` (no por NotificationService).
"""


def client_approved_in_app_title() -> str:
    return "Tu cuenta fue aprobada"


def client_approved_in_app_body(*, first_name: str) -> str:
    return (
        f"Hola {first_name}, tu cuenta fue aprobada. "
        "Revisa tu correo y WhatsApp: allí están tus credenciales para ingresar al portal "
        "y cargar tus datos y documentos."
    )


def client_approved_email_body(
    *,
    first_name: str,
    email: str,
    temp_password: str,
    portal_login_url: str,
    merchant_name: str | None = None,
    android_app_store_url: str = "",
    ios_app_store_url: str = "",
) -> str:
    merchant_block = ""
    if merchant_name:
        merchant_block = f"\nTu cuenta corresponde a {merchant_name}.\n"
    app_block = ""
    if android_app_store_url or ios_app_store_url:
        lines = ["\nDescargá la app móvil"]
        if android_app_store_url:
            lines.append(f"Android (Google Play): {android_app_store_url}")
        if ios_app_store_url:
            lines.append(f"iOS (App Store): {ios_app_store_url}")
        app_block = "\n".join(lines) + "\n"
    return f"""Hola {first_name},
{merchant_block}
¡Bienvenido/a a Epoint!

Tu solicitud fue aprobada. Ya puedes ingresar al portal del cliente para completar tus datos personales y subir la documentación requerida.

Credenciales de acceso
──────────────────────
Portal: {portal_login_url}
Usuario (email): {email}
Contraseña temporal: {temp_password}

En tu primer ingreso deberás cambiar la contraseña temporal.
{app_block}
Si tienes dudas de la plataforma, visita https://epointsolution.com/ o responde este correo: tu mensaje llega al equipo en Epoint.

Saludos,
Equipo Epoint
"""


def client_approved_whatsapp_body(
    *,
    first_name: str,
    email: str,
    temp_password: str,
    portal_login_url: str,
) -> str:
    return (
        f"Hola {first_name}, ¡bienvenido/a a Epoint! Tu cuenta fue aprobada.\n\n"
        f"Ingresa al portal para cargar tus datos y documentos:\n"
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

We're writing from Epoint to remind you that you still have pending items to complete your onboarding.

To continue, sign in to the portal and complete the following:

{items_block}

Client portal: {portal_login_url}

If you already uploaded a document, it may be under review. If it was rejected, please upload it again from the documents section.

If you have platform questions, visit https://epointsolution.com/ or reply to this email: your message reaches the Epoint team in the app.

Best regards,
Epoint Team
"""
    return f"""Hola {first_name},

Te escribimos desde Epoint para recordarte amablemente que aún tienes pendiente completar tu onboarding en la plataforma.

Para continuar con tu proceso, ingresa al portal y completa lo siguiente:

{items_block}

Portal del cliente: {portal_login_url}

Si ya subiste algún documento, puede estar en revisión. Si fue rechazado, vuelve a subirlo desde la sección de documentos.

Si tienes dudas de la plataforma, visita https://epointsolution.com/ o responde este correo: tu mensaje llega al equipo en Epoint.

Saludos,
Equipo Epoint
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
            f"Hi {first_name}, this is a reminder from Epoint that you still have pending onboarding items.\n\n"
            f"Pending:\n{items_block}\n\n"
            f"Sign in to the portal:\n{portal_login_url}\n\n"
            "If a document was rejected, please upload it again from the platform."
        )
    return (
        f"Hola {first_name}, te recordamos desde Epoint que aún tienes pendiente completar tu onboarding.\n\n"
        f"Pendiente:\n{items_block}\n\n"
        f"Ingresa al portal:\n{portal_login_url}\n\n"
        "Si algún documento fue rechazado, vuelve a subirlo desde la plataforma."
    )


def payment_link_email_body(
    *,
    first_name: str,
    amount_formatted: str,
    payment_url: str,
    description: str | None = None,
    merchant_name: str | None = None,
    provider_label: str | None = None,
) -> str:
    merchant_block = ""
    if merchant_name:
        merchant_block = f"\nTu pago corresponde a {merchant_name}.\n"
    description_block = ""
    if description and description.strip():
        description_block = f"\nConcepto: {description.strip()}\n"
    provider_name = provider_label or "nuestro proveedor de pagos"
    return f"""Hola {first_name},
{merchant_block}
Te compartimos tu enlace de pago personalizado para completar tu pago de forma segura a través de {provider_name}.

Monto a pagar: {amount_formatted}
{description_block}
Usa este enlace para completar tu pago:
{payment_url}

Si tienes dudas de la plataforma, visita https://epointsolution.com/ o responde este correo: tu mensaje llega al equipo en Epoint.

Saludos,
Equipo Epoint
"""


def payment_reminder_email_body(
    *,
    first_name: str,
    remaining_formatted: str,
    total_formatted: str,
    payment_url: str,
    paid_formatted: str | None = None,
) -> str:
    paid_line = f"\nYa recibimos {paid_formatted}." if paid_formatted else ""
    return f"""Hola {first_name},

Te recordamos que todavía tienes un saldo pendiente en Epoint.

Monto total: {total_formatted}{paid_line}
Saldo a completar: {remaining_formatted}

Completa tu pago en el siguiente enlace:
{payment_url}

Si tienes dudas de la plataforma, visita https://epointsolution.com/ o responde este correo: tu mensaje llega al equipo en Epoint.

Saludos,
Equipo Epoint
"""


def board_reminder_email_body(
    *,
    first_name: str,
    pending_items: list[str],
    board_url: str,
) -> str:
    items = "\n".join(f"• {item}" for item in pending_items) if pending_items else "• Tareas pendientes en tu tablero"
    return f"""Hola {first_name},

Tu tablero en Epoint tiene tareas pendientes. Complétalas para seguir avanzando: reportes, credenciales u otras tareas abiertas.

Pendientes:
{items}

Ingresa a tu tablero:
{board_url}

Si tienes dudas, visita https://epointsolution.com/ o responde este correo: tu mensaje llega al equipo en Epoint.

Saludos,
Equipo Epoint
"""


def contract_reminder_email_body(
    *,
    first_name: str,
    contract_subject: str,
) -> str:
    return f"""Hola {first_name},

Te recordamos que todavía tienes un contrato pendiente de firma en Epoint.

Contrato: {contract_subject}

Revisa tu bandeja de entrada (también spam): DocuSign te envió o reenvió un correo con el botón para firmar el documento.

Si no encuentras el email de firma, responde este correo y te lo reenviamos.

Saludos,
Equipo Epoint
"""


def client_conversion_welcome_email_body(
    *,
    first_name: str,
    amount_formatted: str,
    merchant_name: str | None = None,
) -> str:
    merchant_block = ""
    if merchant_name:
        merchant_block = f"\nTu proceso corresponde a {merchant_name}.\n"
    return f"""Hola {first_name},
{merchant_block}
¡Bienvenido/a a Epoint!

Confirmamos que tu pago de {amount_formatted} se procesó exitosamente y que completaste todos los requisitos iniciales.

Tu perfil pasará ahora a revisión por parte de nuestro equipo de Onboarding. Una vez que sea aprobado, nos contactaremos con vos por este mismo medio para informarte los próximos pasos.

Gracias por elegirnos.

Si tienes dudas de la plataforma, visita https://epointsolution.com/ o responde este correo: tu mensaje llega al equipo en Epoint.

Equipo Epoint
"""


def staff_welcome_email_body(
    *,
    first_name: str,
    email: str,
    temp_password: str,
    login_url: str,
    role_line: str = "",
) -> str:
    role_block = f"\n{role_line}\n" if role_line.strip() else ""
    return f"""Hola {first_name},
{role_block}
Tu cuenta de empleado en Epoint ya está lista. Puedes ingresar a la plataforma con las credenciales de abajo.

Credenciales de acceso
──────────────────────
Plataforma: {login_url}
Usuario (email): {email}
Contraseña temporal: {temp_password}

En tu primer ingreso debes cambiar la contraseña temporal.

Si tienes dudas de la plataforma, visita https://epointsolution.com/ o responde este correo: tu mensaje llega al equipo en Epoint.

Saludos,
Equipo Epoint
"""


def password_reset_email_body(
    *,
    first_name: str,
    reset_url: str,
    expire_minutes: int,
) -> str:
    return f"""Hola {first_name},

Recibimos una solicitud para restablecer la contraseña de tu cuenta en Epoint.

Para elegir una nueva contraseña, abre el siguiente enlace (válido por {expire_minutes} minutos):

{reset_url}

Si no solicitaste este cambio, ignorá este correo. Tu contraseña actual seguirá siendo la misma.

Saludos,
Equipo Epoint
"""
