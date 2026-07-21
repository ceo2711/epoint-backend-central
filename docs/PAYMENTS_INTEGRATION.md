# Integración de pagos — Authorize.net y PayPal

Este documento describe cómo conectar el CRM con **Authorize.net** y **PayPal** para generar links de pago personalizados por prospecto/cliente.

## Resumen del flujo

1. El vendedor crea un link en **Pagos** (o desde el detalle del prospecto) con nombre, email, monto y proveedor.
2. El backend crea un checkout en el proveedor elegido y guarda el link en `payment_links`.
3. El cliente abre el link (URL del proveedor o `/pagar/{token}` en modo desarrollo).
4. Al completar el pago, el webhook (o el retorno PayPal) marca el link como `paid`.
5. Si el link está vinculado a un prospecto, el pipeline avanza y puede convertirse en cliente.

## Variables de entorno

Agregá en `backend/.env`:

```env
PAYMENTS_ENABLED=true
PAYMENTS_DEFAULT_PROVIDER=authorize   # authorize | paypal
FRONTEND_URL=https://tu-frontend.com
BACKEND_PUBLIC_URL=https://tu-backend.com

# Authorize.net
AUTHORIZE_API_LOGIN_ID=tu_api_login_id
AUTHORIZE_TRANSACTION_KEY=tu_transaction_key
AUTHORIZE_SIGNATURE_KEY=tu_signature_key_webhook   # opcional en dev
AUTHORIZE_ENV=sandbox                            # sandbox | production

# PayPal
PAYPAL_CLIENT_ID=tu_client_id
PAYPAL_CLIENT_SECRET=tu_client_secret
PAYPAL_WEBHOOK_ID=WH-xxxxxxxx                      # ID del webhook en PayPal Developer
PAYPAL_ENV=sandbox                               # sandbox | production
```

### Modo desarrollo (stub)

Si **ningún** proveedor tiene credenciales, la app entra en **modo stub**:
- El link apunta a `{FRONTEND_URL}/pagar/{token}`
- El cliente puede simular el pago con un botón
- Útil para probar prospectos y conversión sin APIs reales

---

## Authorize.net

### Qué necesitás

| Requisito | Dónde obtenerlo |
|-----------|-----------------|
| Cuenta Authorize.net | [authorize.net](https://www.authorize.net/) |
| API Login ID | Merchant Interface → Account → Settings → API Credentials & Keys |
| Transaction Key | Misma pantalla (generar nueva key) |
| Signature Key (webhooks) | Account → Webhooks → Signature Key |

### Entornos

| `AUTHORIZE_ENV` | API | Página de pago hospedada |
|-----------------|-----|--------------------------|
| `sandbox` | `https://apitest.authorize.net/xml/v1/request.api` | `https://test.authorize.net/payment/payment` |
| `production` | `https://api.authorize.net/xml/v1/request.api` | `https://accept.authorize.net/payment/payment` |

### Cómo funciona en el CRM

- Se usa **Accept Hosted** (`getHostedPaymentPageRequest`).
- Cada link guarda el `public_token` del CRM como `invoiceNumber` (máx. 20 caracteres).
- El cliente paga en la página hospedada de Authorize.net.
- Al volver a `{FRONTEND_URL}/pagar/{token}?paid=1`, el CRM puede confirmar el estado.

### Webhook

Registrá en Authorize.net → Webhooks:

```
POST {BACKEND_PUBLIC_URL}/api/v1/payments/webhooks/authorize
```

Eventos recomendados:
- `net.authorize.payment.authcapture.created`
- `net.authorize.payment.capture.created`

El backend busca el link por `invoiceNumber` (= `public_token`) y lo marca como pagado.

### Checklist Authorize.net

- [ ] Cuenta sandbox o producción activa
- [ ] API Login ID + Transaction Key en `.env`
- [ ] `AUTHORIZE_ENV` correcto
- [ ] `BACKEND_PUBLIC_URL` accesible desde internet (ngrok en local)
- [ ] Webhook configurado apuntando al endpoint del CRM
- [ ] Probar crear link desde `/pagos` y completar pago de prueba

---

## PayPal

Guía completa paso a paso: **[PAYPAL_SETUP.md](./PAYPAL_SETUP.md)**.

Resumen corto:

| Requisito | Dónde |
|-----------|--------|
| App REST + Client ID / Secret | [developer.paypal.com](https://developer.paypal.com/) → Apps & Credentials (Sandbox) |
| Variables | `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_ENV=sandbox` |
| Checkout | Orders API v2 · `GUEST_CHECKOUT` · retorno `{FRONTEND_URL}/pagar/{token}?paid=1` |
| Webhook | `POST {BACKEND_PUBLIC_URL}/api/v1/payments/webhooks/paypal` |

### Checklist PayPal

- [ ] Seguir [PAYPAL_SETUP.md](./PAYPAL_SETUP.md)
- [ ] App REST Sandbox + keys en `.env`
- [ ] Probar link → pagar → estado `paid` + notificación
- [ ] (Opcional) Webhook con `BACKEND_PUBLIC_URL` público

---

## Endpoints del CRM

| Endpoint | Uso |
|----------|-----|
| `GET /api/v1/payments/config` | Estado de proveedores (UI Pagos) |
| `POST /api/v1/payments/links` | Crear link personalizado |
| `GET /api/v1/payments/public/{token}` | Página pública de pago |
| `POST /api/v1/payments/public/{token}/confirm-return` | Confirmar retorno PayPal |
| `POST /api/v1/payments/webhooks/paypal` | Webhook PayPal |
| `POST /api/v1/payments/webhooks/authorize` | Webhook Authorize.net |
| `POST /api/v1/prospects/{id}/link-payment` | Vincular link existente a prospecto |

---

## Prospectos

Al crear un link desde el detalle del prospecto:
- Se envía `prospect_id` en el payload
- El link queda vinculado automáticamente
- Al pagarse, el prospecto pasa a `PAGO_COMPLETADO`
- Si reunión + contrato + pago están completos → conversión automática a cliente

---

## Email al cliente

Al generar un link (desde Pagos o desde un prospecto), el CRM puede enviar automáticamente un correo brandeado de **ePoint** al email del cliente.

### Variables de entorno (Resend)

```env
RESEND_API_KEY=re_xxxxxxxx
EMAIL_FROM=pagos@tu-dominio.com
EMAIL_FROM_NAME=ePoint Central
EMAIL_DEV_REDIRECT_TO=          # opcional: redirige todos los emails en dev
NOTIFICATIONS_DRY_RUN=true      # simula envíos sin mandar nada real
FRONTEND_URL=https://tu-frontend.com
```

### Contenido del email

- Logo y branding ePoint (misma plantilla que bienvenida y reset de contraseña)
- Nombre del cliente, monto y concepto (si hay descripción)
- Botón **Completar pago** con el link personalizado
- Link de respaldo en texto plano

### URL en el email

| Modo | Qué recibe el cliente |
|------|------------------------|
| **Con PayPal/Authorize configurado** | Preferentemente la URL de **checkout del proveedor** (pago directo) |
| **Fallback / stub** | `{FRONTEND_URL}/pagar/{token}` — si hay checkout, la página redirige sola |

Documentación PayPal: [PAYPAL_SETUP.md](./PAYPAL_SETUP.md).

### Desarrollo local

- Con `NOTIFICATIONS_DRY_RUN=true`: el email se registra en logs pero no se envía.
- Con `EMAIL_DEV_REDIRECT_TO=tu@email.com`: todos los correos van a tu casilla (útil con Resend sandbox).
- Verificá dominio en [resend.com/domains](https://resend.com/domains) para producción.

### Regenerar plantilla HTML

Si modificás `frontend/emails/PaymentLinkEmail.tsx`:

```bash
cd frontend && npm run emails:build
```

---

## Desarrollo local con webhooks

Los proveedores no pueden llamar a `localhost`. Opciones:

1. **ngrok** (recomendado para probar webhooks):
   ```bash
   ngrok http 8000
   ```
   Usá la URL HTTPS en `BACKEND_PUBLIC_URL`.

2. **Solo stub** (sin webhooks): dejá las credenciales vacías y usá «Simular pago» en `/pagar/{token}`.

---

## Stripe (legacy)

Stripe fue removido de la UI. Los links antiguos con `provider=stripe` siguen listándose, pero no se pueden crear nuevos links con Stripe.

---

## Soporte

Si un link se crea pero el checkout falla, revisá los logs del backend (`PaymentProviderError`). En desarrollo sin credenciales, el sistema usa automáticamente la página interna `/pagar/{token}`.
