# Integración de correo de bienvenida (cliente aprobado)

Este módulo concentra el envío del **email de bienvenida con credenciales del portal** cuando un cliente es aprobado en el CRM.

Hoy la función está en **modo stub** (solo registra en logs y devuelve `True`). La implementación real va en un único lugar.

---

## Dónde implementar

| Archivo | Qué hacer |
|---------|-----------|
| **`client_welcome.py`** → `send_client_welcome_email()` | **Aquí va toda la lógica de envío** (proveedor, API, errores, reintentos). |
| `notifications/templates.py` → `client_approved_email_body()` | Solo el **texto** del correo (ya existe). Reutilizarlo o sustituirlo por HTML. |
| `core/config.py` + `.env` | Variables del proveedor elegido (API key, remitente, etc.). |
| `clients.py` → `approve_client()` | **No tocar** salvo que cambie el momento del envío. Ya llama a `send_client_welcome_email()`. |
| `scripts/send_client_welcome_email.py` | **No tocar** para el flujo normal. Sirve para pruebas y reenvíos manuales. |

---

## Flujo actual

```
Admin aprueba cliente (API)
        │
        ▼
ClientService.approve_client()
        │
        ├── send_client_welcome_email(payload)   ← email de bienvenida (este módulo)
        │
        └── NotificationService.notify()         ← IN_APP + WhatsApp (no email)
```

El canal **EMAIL** ya no forma parte de `CLIENT_APPROVED` en `NotificationService`. El correo de bienvenida quedó desacoplado a propósito para que elijas el proveedor sin mezclarlo con otras notificaciones.

---

## Datos disponibles (`ClientWelcomeEmailPayload`)

Al implementar el envío recibirás:

| Campo | Descripción |
|-------|-------------|
| `recipient_email` | Email del cliente (destinatario). |
| `first_name` | Nombre para personalizar el saludo. |
| `temp_password` | Contraseña temporal del portal. |
| `portal_login_url` | URL de login (desde `PORTAL_LOGIN_URL` / settings). |
| `client_id` | ID del cliente (opcional; útil para logs y auditoría). |

Ejemplo de uso de la plantilla de texto:

```python
from app.core.config import get_settings
from app.services.notifications.templates import client_approved_email_body

settings = get_settings()
subject = "¡Bienvenido a Epoint!"
body = client_approved_email_body(
    first_name=payload.first_name,
    email=payload.recipient_email,
    temp_password=payload.temp_password,
    portal_login_url=payload.portal_login_url,
)
```

---

## Pasos para integrar un proveedor

### 1. Elegir servicio

Opciones habituales:

- **SendGrid** — ya está en `requirements.txt` y hay referencia en `notifications/providers.py` (`EmailProvider`).
- **Resend**, **Mailgun**, **Amazon SES**, **SMTP** — requieren SDK o cliente HTTP propio.

No hace falta decidir ahora; el contrato del módulo es el mismo: recibir `ClientWelcomeEmailPayload` y devolver `bool`.

### 2. Configurar variables de entorno

En `.env` (local) y en Heroku (`dev-epoint-crm-backend` → Settings → Config Vars).

**Si usás SendGrid** (mínimo):

```env
SENDGRID_API_KEY=SG.xxx
EMAIL_FROM=notificaciones@tudominio.com
EMAIL_FROM_NAME=Epoint Corporation
NOTIFICATIONS_DRY_RUN=false
```

`EMAIL_FROM` debe ser un remitente verificado en el panel del proveedor.

**Si usás otro proveedor**, agregar campos en `app/core/config.py` (por ejemplo `resend_api_key`, `smtp_host`, etc.) y documentarlos en `.env.example`.

### 3. Implementar `send_client_welcome_email()`

Archivo: **`client_welcome.py`**.

Checklist de implementación:

1. Leer settings con `get_settings()`.
2. Respetar `notifications_dry_run`: si es `True`, solo loguear y devolver `True` (útil en desarrollo).
3. Construir asunto y cuerpo (texto o HTML).
4. Llamar al API del proveedor.
5. En éxito → `return True`.
6. En error → loguear con `logger.exception(...)`, `return False`.
7. No lanzar excepciones hacia arriba salvo que quieras abortar la aprobación (hoy la aprobación continúa aunque el email falle).

**Ejemplo esquemático con SendGrid:**

```python
def send_client_welcome_email(payload: ClientWelcomeEmailPayload) -> bool:
    settings = get_settings()
    if settings.notifications_dry_run:
        logger.info("[DRY RUN] welcome email → %s", payload.recipient_email)
        return True
    if not settings.sendgrid_api_key:
        logger.warning("SENDGRID_API_KEY no configurada")
        return False

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        body = client_approved_email_body(...)
        message = Mail(
            from_email=(settings.email_from, settings.email_from_name),
            to_emails=payload.recipient_email,
            subject="¡Bienvenido a Epoint!",
            plain_text_content=body,
        )
        SendGridAPIClient(settings.sendgrid_api_key).send(message)
        return True
    except Exception:
        logger.exception("Error enviando welcome email a %s", payload.recipient_email)
        return False
```

### 4. (Opcional) Extraer un adaptador reutilizable

Si más adelante hay otros correos transaccionales (rechazo, documento vencido, etc.), conviene:

```
app/services/email/
├── __init__.py
├── client_welcome.py      # orquesta el caso de uso
├── provider.py            # interfaz + implementación SendGrid/Resend/...
└── README.md
```

Por ahora basta con completar `client_welcome.py`.

### 5. Plantilla HTML (recomendado en producción)

`client_approved_email_body()` devuelve texto plano. Para HTML:

- Crear `templates/email/client_welcome.html` (o similar), **o**
- Usar plantillas del proveedor (SendGrid Dynamic Templates, etc.).

Mantener una versión texto plano mejora la entregabilidad y clientes de correo sin HTML.

### 6. Probar

**Unit test** (ya existe stub):

```bash
pytest tests/unit/test_client_welcome_email.py -v
```

Actualizar el test cuando la implementación deje de ser stub (mockear el proveedor).

**Script manual** (sin aprobar cliente en UI):

```bash
cd backend
python scripts/send_client_welcome_email.py \
  --email cliente@ejemplo.com \
  --first-name Juan \
  --temp-password "TempPass123!"
```

**Flujo completo:** aprobar un cliente desde el CRM y verificar bandeja de entrada + logs del backend.

### 7. Desplegar

Rama de trabajo: `feature/send-email`.

Tras implementar:

1. Commit en `feature/send-email`.
2. Merge a `dev` cuando esté listo.
3. Push a GitHub y Heroku: `git push heroku dev:main`.
4. Configurar las variables del proveedor en Heroku.

---

## Qué no modificar (salvo necesidad)

| Componente | Motivo |
|------------|--------|
| `NotificationService` + `EmailProvider` | Siguen usándose para **otros** eventos (`NEW_CLIENT_PENDING_REVIEW`, `CLIENT_REJECTED`, etc.). El welcome email no pasa por ahí. |
| `approve_client()` | Ya invoca `send_client_welcome_email()` con el payload correcto. |
| Frontend | No interviene en el envío; es 100 % backend. |

---

## Seguridad y buenas prácticas

- **Contraseña temporal:** solo viaja en el email de bienvenida; no loguear `temp_password` en producción.
- **Remitente verificado:** configurar SPF/DKIM en el dominio del proveedor.
- **Dry run:** mantener `NOTIFICATIONS_DRY_RUN=true` en desarrollo local si no querés envíos reales.
- **Errores:** decidir si un fallo de email debe notificar al equipo (futuro: cola + reintento con Celery).

---

## Resumen

1. Implementar en **`client_welcome.py`** → `send_client_welcome_email()`.
2. Reutilizar **`client_approved_email_body()`** o crear plantilla HTML.
3. Configurar credenciales en **`.env`** / **Heroku**.
4. Probar con **`scripts/send_client_welcome_email.py`** y con aprobación real en CRM.

Cuando elijas proveedor, el cambio principal es solo el bloque de envío dentro de `send_client_welcome_email()`.
