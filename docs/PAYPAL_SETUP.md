# Configuración PayPal — ePoint CRM

Guía paso a paso para integrar [PayPal Checkout](https://developer.paypal.com/) (Orders API v2) con ePoint CRM. Permite a vendedores y administradores generar **links de pago** desde **Pagos** (`/pagos`) o desde el detalle de un **prospecto**.

**Rutas en la app:** `/pagos` (staff) · `/pagar/{token}` (cliente, pública / retorno)  
**Roles con acceso:** `ADMIN`, `BRANCH_MANAGER`, `SALES_REP`  
**Modelo de integración:** cuenta **única de empresa** vía variables de entorno del backend (igual que DocuSign)

---

## Tabla de contenidos

1. [Resumen](#1-resumen)
2. [Requisitos previos](#2-requisitos-previos)
3. [Paso 1 — Cuenta Developer y Sandbox](#3-paso-1--cuenta-developer-y-sandbox)
4. [Paso 2 — Crear / abrir la app REST](#4-paso-2--crear--abrir-la-app-rest)
5. [Paso 3 — Variables de entorno (backend)](#5-paso-3--variables-de-entorno-backend)
6. [Paso 4 — Webhook (recomendado)](#6-paso-4--webhook-recomendado)
7. [Paso 5 — Verificar la integración](#7-paso-5--verificar-la-integración)
8. [Paso 6 — Probar el flujo completo](#8-paso-6--probar-el-flujo-completo)
9. [Uso en la aplicación](#9-uso-en-la-aplicación)
10. [Pasar a producción (Live)](#10-pasar-a-producción-live)
11. [Despliegue en Heroku](#11-despliegue-en-heroku)
12. [API REST](#12-api-rest)
13. [Arquitectura de archivos](#13-arquitectura-de-archivos)
14. [Solución de problemas](#14-solución-de-problemas)

---

## 1. Resumen

| Aspecto | Detalle |
|---------|---------|
| **Producto PayPal** | Checkout estándar — Orders API v2 (`intent: CAPTURE`) |
| **Credenciales** | Solo en el **backend** (`PAYPAL_*`) |
| **UI de configuración** | No existe — se configura por `.env` / Heroku Config Vars |
| **Experiencia del pagador** | Preferencia `GUEST_CHECKOUT` (tarjeta sin cuenta PayPal cuando PayPal lo permite) |
| **Email al cliente** | Botón con URL de checkout PayPal (si existe); si no, portal `/pagar/{token}` |
| **Confirmación** | Retorno a `/pagar/{token}?paid=1` + capture; webhook opcional de respaldo |
| **Prospectos** | Link vinculado → historial; al pagar → `PAGO_COMPLETADO` y posible conversión automática |

### Sandbox vs producción

| Entorno | `PAYPAL_ENV` | API |
|---------|--------------|-----|
| **Sandbox (pruebas)** | `sandbox` | `https://api-m.sandbox.paypal.com` |
| **Live (real)** | `production` | `https://api-m.paypal.com` |

> Usá siempre **sandbox** hasta validar el flujo. Los pagos sandbox no mueven dinero real.

### Desde Argentina

Podés crear cuenta en [PayPal Developer](https://developer.paypal.com/) y apps **sandbox** sin problema. Para **Live**, la empresa necesita una cuenta Business PayPal operativa en el país donde cobre.

---

## 2. Requisitos previos

- Backend ePoint CRM con migraciones de pagos aplicadas (`payment_links`, etc.).
- `FRONTEND_URL` apuntando al frontend (retorno post-pago y página `/pagar/{token}`).
- Usuario staff con permisos `payments:read` y `payments:create` (roles de ventas / admin).
- Email operativo (Resend) si querés que el link se envíe por correo al crear el pago.
- Cuenta en [PayPal Developer](https://developer.paypal.com/).

### Lo que NO se necesita

- Variables `PAYPAL_*` en el frontend.
- Panel de configuración en la UI.
- OAuth por vendedor (a diferencia de Calendly).
- Cuenta PayPal del **cliente** (puede pagar como invitado / con tarjeta cuando PayPal lo habilite).

---

## 3. Paso 1 — Cuenta Developer y Sandbox

1. Entrá a [https://developer.paypal.com](https://developer.paypal.com) e iniciá sesión.
2. Confirmá que estás en **Sandbox** (no Live).
3. (Opcional) En el onboarding, elegí **PayPal Checkout** — es el producto que usa el CRM. Podés **Skip** el resto del wizard; lo crítico son las credenciales.

### Cuentas sandbox de prueba

1. Menú **Testing Tools** → **Sandbox accounts**  
   (o [Accounts](https://developer.paypal.com/dashboard/accounts)).
2. Vas a ver al menos:
   - Una cuenta **Business** (cobrador, asociada a tu app).
   - Una cuenta **Personal** (comprador de prueba).
3. Anotá email/password de la **Personal** por si el sandbox no muestra guest checkout y necesitás completar una prueba con login.

> En sandbox a veces PayPal prioriza login. En Live, con `GUEST_CHECKOUT`, el pagador suele ver opción de tarjeta sin crear cuenta.

---

## 4. Paso 2 — Crear / abrir la app REST

1. Andá a **Apps & Credentials**.
2. Pestaña **Sandbox**.
3. En **REST API apps**:
   - Usá la **Default Application**, o
   - **Create App** (ej. `epoint-crm-sandbox`).
4. Abrí la app y copiá:
   - **Client ID** → `PAYPAL_CLIENT_ID`
   - **Secret** (Show) → `PAYPAL_CLIENT_SECRET`

> Nunca subas el Secret a Git ni lo pegues en chats públicos. Si se filtró, regeneralo en el dashboard.

---

## 5. Paso 3 — Variables de entorno (backend)

En `backend/.env`:

```env
PAYMENTS_ENABLED=true
PAYMENTS_DEFAULT_PROVIDER=paypal

FRONTEND_URL=http://localhost:3000
BACKEND_PUBLIC_URL=http://localhost:8000

PAYPAL_CLIENT_ID=Axxxxxxxx...
PAYPAL_CLIENT_SECRET=Exxxxxxxx...
PAYPAL_ENV=sandbox
PAYPAL_WEBHOOK_ID=
```

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `PAYPAL_CLIENT_ID` | Sí | Client ID de la app Sandbox/Live |
| `PAYPAL_CLIENT_SECRET` | Sí | Secret de la app |
| `PAYPAL_ENV` | No (default `sandbox`) | `sandbox` o `production` |
| `PAYPAL_WEBHOOK_ID` | No al inicio | ID del webhook (opcional; el retorno del checkout ya confirma el pago) |
| `FRONTEND_URL` | Sí | Base del portal `/pagar/{token}` y `?paid=1` |
| `BACKEND_PUBLIC_URL` | Para webhooks | URL pública del API (Heroku / ngrok) |
| `PAYMENTS_ENABLED` | No | `false` deshabilita creación y cobro |
| `PAYMENTS_DEFAULT_PROVIDER` | No | `paypal` o `authorize` |

Reiniciá el backend después de guardar.

### Considerado “configurado”

El backend marca PayPal como `configured: true` en `GET /payments/config` cuando existen **Client ID** y **Secret**.

---

## 6. Paso 4 — Webhook (recomendado)

El flujo principal marca el pago al **volver** del checkout (`confirm-return` + capture). El webhook es respaldo si el usuario cierra el navegador antes de volver.

1. Developer Dashboard → **Webhooks** (o Apps → tu app → Webhooks) en **Sandbox**.
2. **Add webhook** con URL:

```text
https://{BACKEND_PUBLIC_URL}/api/v1/payments/webhooks/paypal
```

Ejemplo Heroku:

```text
https://dev-epoint-crm-backend-3807e7e86dca.herokuapp.com/api/v1/payments/webhooks/paypal
```

3. Eventos sugeridos:
   - `CHECKOUT.ORDER.APPROVED`
   - `PAYMENT.CAPTURE.COMPLETED`
4. Copiá el **Webhook ID** → `PAYPAL_WEBHOOK_ID` (si lo usás).

### Local

PayPal no puede llamar a `localhost`. Opciones:

```bash
ngrok http 8000
```

Poné la URL HTTPS de ngrok en `BACKEND_PUBLIC_URL` y en el webhook.  
Sin ngrok, podés probar solo con el **retorno** del checkout (`?paid=1`).

---

## 7. Paso 5 — Verificar la integración

### 1. Config (con token de staff)

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/payments/config
```

Esperado (fragmento):

```json
{
  "payments_enabled": true,
  "default_provider": "paypal",
  "stub_mode": false,
  "providers": [
    { "provider": "authorize", "configured": false, "label": "Authorize.net" },
    { "provider": "paypal", "configured": true, "label": "PayPal" }
  ]
}
```

- `stub_mode: false` → hay al menos un proveedor con credenciales.
- En la UI de **Pagos**, el selector debe mostrar **PayPal**.

### 2. Frontend

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

No hace falta ninguna variable PayPal en el frontend.

---

## 8. Paso 6 — Probar el flujo completo

1. Login como vendedor o admin.
2. **Pagos** → crear link con proveedor **PayPal** (monto chico, ej. `1.00` USD), o desde un **prospecto** → **Generar link**.
3. Si enviás email: el botón del correo debería abrir **PayPal** (checkout), no una pantalla intermedia innecesaria.
4. Completá el pago en sandbox (guest o cuenta Personal).
5. PayPal redirige a `{FRONTEND_URL}/pagar/{token}?paid=1`.
6. El CRM captura la orden y marca el link como **paid**.
7. Si había prospecto vinculado:
   - Historial: “Pago completado” (y antes “Link de pago generado”).
   - Estado → `PAGO_COMPLETADO` cuando corresponda.
8. El vendedor recibe notificación in-app `PAYMENT_LINK_COMPLETED`.

### Cancelar un link

Desde **Pagos**, cancelá un link **pending**. Si está vinculado a un prospecto, el historial registra **Link de pago cancelado**. Podés generar otro link desde el prospecto.

---

## 9. Uso en la aplicación

### Staff (`/pagos`)

| Acción | Descripción |
|--------|-------------|
| Crear link | Datos del cliente, monto, proveedor PayPal, email opcional |
| Buscar prospecto | Autocompleta datos y vincula `prospect_id` |
| Historial | Abrir / copiar / cancelar / registrar cliente post-pago |

### Prospecto

| Acción | Descripción |
|--------|-------------|
| Generar link | Crea + vincula + opcionalmente envía email |
| Ver links | Lista pending / paid / cancelled |
| Nuevo link | Útil si el anterior fue cancelado |

### Cliente (pagador)

1. Abre el link del email (checkout PayPal) o `/pagar/{token}` (redirige solo a PayPal si está pending).
2. Paga.
3. Vuelve a ePoint y ve confirmación de pago recibido.

---

## 10. Pasar a producción (Live)

1. En Developer Dashboard, cambiá a **Live**.
2. Creá / abrí la app REST de producción.
3. Copiá Client ID y Secret **Live**.
4. Configurá webhook Live con la URL del backend de producción.
5. Variables:

```env
PAYPAL_CLIENT_ID=...        # Live
PAYPAL_CLIENT_SECRET=...    # Live
PAYPAL_ENV=production
PAYPAL_WEBHOOK_ID=...       # Live webhook id
FRONTEND_URL=https://tu-frontend-produccion
BACKEND_PUBLIC_URL=https://tu-backend-produccion
```

6. La cuenta Business de la **empresa** debe estar verificada para recibir fondos reales.
7. Probá un cobro mínimo real y confirmá liquidación en PayPal.

> No mezcles keys sandbox con `PAYPAL_ENV=production` (ni al revés).

---

## 11. Despliegue en Heroku

App backend (ejemplo `dev-epoint-crm-backend`):

```bash
heroku config:set PAYMENTS_ENABLED=true -a dev-epoint-crm-backend
heroku config:set PAYMENTS_DEFAULT_PROVIDER=paypal -a dev-epoint-crm-backend
heroku config:set PAYPAL_CLIENT_ID=... -a dev-epoint-crm-backend
heroku config:set PAYPAL_CLIENT_SECRET=... -a dev-epoint-crm-backend
heroku config:set PAYPAL_ENV=sandbox -a dev-epoint-crm-backend
heroku config:set FRONTEND_URL=https://dev-epoint-crm-frontend-4985af85e0a2.herokuapp.com -a dev-epoint-crm-backend
heroku config:set BACKEND_PUBLIC_URL=https://dev-epoint-crm-backend-3807e7e86dca.herokuapp.com -a dev-epoint-crm-backend
```

También podés usar el script del repo que sube vars desde `backend/.env` (sin commitear secretos):

```bash
cd backend && python scripts/push_heroku_backend_config.py
```

Checklist post-deploy:

1. Reinicio / release del backend.
2. `GET /payments/config` → PayPal `configured: true`.
3. Webhook Sandbox apuntando al `BACKEND_PUBLIC_URL` de Heroku.
4. Crear un link de prueba y completar un pago sandbox.

---

## 12. API REST

Prefijo: `/api/v1/payments`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| `GET` | `/config` | Staff | Estado de proveedores |
| `GET` | `/links` | Staff | Listar links |
| `POST` | `/links` | Staff | Crear link (PayPal crea la orden) |
| `POST` | `/links/{id}/cancel` | Staff | Cancelar pending (+ historial prospecto) |
| `GET` | `/public/{token}` | Público | Datos del cobro / checkout_url |
| `POST` | `/public/{token}/confirm-return` | Público | Retorno post-PayPal + capture |
| `POST` | `/webhooks/paypal` | Público | Webhook PayPal |

Prospectos:

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/prospects/{id}/link-payment` | Vincular link existente |
| `GET` | `/prospects/{id}` | Incluye `payment_link` + `payment_links[]` |

---

## 13. Arquitectura de archivos

### Backend

```
backend/app/
├── api/v1/payments.py                 # REST + webhook PayPal
├── core/config.py                     # PAYPAL_* / PAYMENTS_*
├── models/payment_link.py
├── schemas/payment.py
└── services/payments/
    ├── service.py                     # Crear link, capture, cancel, email
    └── paypal_provider.py             # Orders API v2 + GUEST_CHECKOUT
```

### Frontend

```
frontend/src/features/payments/
├── components/
│   ├── PagosPage.tsx
│   ├── PaymentLinkForm.tsx
│   ├── PaymentLinkList.tsx
│   └── PublicPaymentPage.tsx          # Redirect automático al checkout
└── utils/providers.ts
```

Documentación relacionada:

- [PAYMENTS_INTEGRATION.md](./PAYMENTS_INTEGRATION.md) — overview Authorize + PayPal
- [AUTHORIZE_SETUP.md](./AUTHORIZE_SETUP.md) — guía paso a paso de Authorize.net
- [PAYPAL_SETUP.md](./PAYPAL_SETUP.md) — guía equivalente de PayPal

---

## 14. Solución de problemas

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| PayPal no aparece en el selector | Sin Client ID/Secret o backend sin reiniciar | Revisar `.env` y reiniciar API |
| `stub_mode: true` | Ningún proveedor configurado | Completar `PAYPAL_CLIENT_ID` + `SECRET` |
| Error al crear link (502) | Credenciales inválidas o app Live/Sandbox mezclada | Verificar `PAYPAL_ENV` y keys del mismo entorno |
| Email abre pantalla intermedia vieja | Link generado antes del cambio de URL | Generar un link **nuevo** |
| PayPal pide login sí o sí | Limitación sandbox / país | Probar guest; o cuenta Personal sandbox |
| Paga pero CRM no marca `paid` | Falló retorno o capture | Revisar logs; configurar webhook; abrir `?paid=1` |
| Webhook no llega en local | `localhost` no público | Usar ngrok o probar solo en Heroku |
| Cancelado no sale en historial | Cancelación anterior al feature | Solo cancelaciones **nuevas** registran historial |

### Cómo confirma el CRM el pago

1. Cliente aprueba en PayPal.
2. Redirect a `{FRONTEND_URL}/pagar/{token}?paid=1` (a veces con `token` = order id de PayPal).
3. Frontend llama `POST /payments/public/{token}/confirm-return`.
4. Backend consulta/captura la orden y marca `paid`.
5. Si hay `prospect_id`, avanza el pipeline y notifica al vendedor.

---

## Checklist rápido

- [ ] App REST en PayPal Developer (Sandbox)
- [ ] `PAYPAL_CLIENT_ID` + `PAYPAL_CLIENT_SECRET` en `backend/.env`
- [ ] `PAYPAL_ENV=sandbox`
- [ ] `FRONTEND_URL` correcto
- [ ] Backend reiniciado → `GET /payments/config` muestra PayPal configurado
- [ ] Crear link desde `/pagos` o prospecto
- [ ] Completar pago sandbox
- [ ] Ver estado `paid` + notificación
- [ ] (Opcional) Webhook + `BACKEND_PUBLIC_URL`
- [ ] (Producción) App Live + `PAYPAL_ENV=production`

Cuando eso esté verde, la integración PayPal del CRM está lista.
