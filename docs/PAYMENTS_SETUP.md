# Configuración de Pagos — ePoint CRM

Guía para integrar **Stripe** y **Authorize.net** con ePoint CRM. Permite a vendedores y administradores generar **links de pago** para clientes desde la vista **Pagos** (`/pagos`).

**Ruta en la app:** `/pagos` (staff) · `/pagar/{token}` (cliente, pública)  
**Roles con acceso:** `ADMIN` y `SALES_REP`  
**Modelo de integración:** cuenta **única de empresa** vía variables de entorno del backend (igual que DocuSign)

---

## Tabla de contenidos

1. [Resumen](#1-resumen)
2. [Requisitos previos](#2-requisitos-previos)
3. [Flujo de negocio](#3-flujo-de-negocio)
4. [Paso 1 — Variables generales](#4-paso-1--variables-generales)
5. [Paso 2 — Configurar Stripe](#5-paso-2--configurar-stripe)
6. [Paso 3 — Configurar Authorize.net](#6-paso-3--configurar-authorizenet)
7. [Paso 4 — Verificar la integración](#7-paso-4--verificar-la-integración)
8. [Modo stub (sin credenciales)](#8-modo-stub-sin-credenciales)
9. [Uso en la aplicación](#9-uso-en-la-aplicación)
10. [Despliegue en Heroku](#10-despliegue-en-heroku)
11. [API REST](#11-api-rest)
12. [Arquitectura de archivos](#12-arquitectura-de-archivos)
13. [Solución de problemas](#13-solución-de-problemas)

---

## 1. Resumen

| Aspecto | Detalle |
|---------|---------|
| **Proveedores** | Stripe Checkout · Authorize.net (Accept Hosted / payment links) |
| **Credenciales** | Solo en variables de entorno del **backend** |
| **UI de configuración** | **No existe** — el admin de sistemas configura el servidor |
| **Vista staff** | **Igual para ADMIN y SALES_REP**: crear links, ver historial, registrar cliente post-pago |
| **Notificación** | Al completar el pago, el vendedor que creó el link recibe `PAYMENT_LINK_COMPLETED` |
| **Alta en CRM** | Tras el pago, el vendedor puede registrar al cliente en **Clientes** |

### Demo vs producción

| Proveedor | Sandbox / test | Producción |
|-----------|----------------|------------|
| **Stripe** | Claves `sk_test_...` / `pk_test_...` | Claves `sk_live_...` / `pk_live_...` |
| **Authorize.net** | `AUTHORIZE_ENV=sandbox` | `AUTHORIZE_ENV=production` |

> Usá siempre el entorno de prueba hasta validar el flujo completo. Los pagos en sandbox no mueven dinero real.

---

## 2. Requisitos previos

- Backend ePoint CRM con migración **019** aplicada (`payment_links`, `payment_settings`).
- `FRONTEND_URL` apuntando al frontend (para URLs de checkout y página pública `/pagar/{token}`).
- Usuario con rol `ADMIN` o `SALES_REP` y permisos `payments:read` + `payments:create` (incluidos en `scripts/seed.py`).
- Cuenta en [Stripe](https://dashboard.stripe.com/) y/o [Authorize.net](https://www.authorize.net/) según el proveedor que vayas a usar.

### Lo que NO se necesita

- Variables de pago en el frontend (solo `NEXT_PUBLIC_API_URL`).
- Panel de configuración en la UI de `/pagos`.
- OAuth por vendedor (como Calendly).

---

## 3. Flujo de negocio

```
Vendedor/Admin en /pagos
    → Completa monto + datos del cliente
    → Elige proveedor (Stripe o Authorize.net)
    → Se genera link de pago (URL compartible)

Cliente abre el link
    → Paga en checkout del proveedor (o simula en modo stub)
    → Estado del link pasa a paid

Vendedor recibe notificación in-app
    → Desde /pagos puede "Registrar cliente" en el CRM
```

---

## 4. Paso 1 — Variables generales

Agregá en `backend/.env` (o en Heroku Config Vars):

```env
# Habilitar o deshabilitar la generación de links (true/false)
PAYMENTS_ENABLED=true

# Proveedor preseleccionado en el formulario: stripe | authorize
PAYMENTS_DEFAULT_PROVIDER=stripe

# URL del frontend (obligatoria para links públicos y redirects)
FRONTEND_URL=http://localhost:3000
```

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `PAYMENTS_ENABLED` | No (default `true`) | Si es `false`, no se pueden crear links ni pagar en la página pública |
| `PAYMENTS_DEFAULT_PROVIDER` | No (default `stripe`) | Proveedor por defecto en el formulario de `/pagos` |
| `FRONTEND_URL` | Sí (recomendada) | Base para `/pagar/{token}` y URLs de retorno del checkout |

### Frontend

No requiere variables de pago. Solo:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

---

## 5. Paso 2 — Configurar Stripe

### 5.1 Obtener claves en Stripe Dashboard

1. Entrá a [Stripe Dashboard → Developers → API keys](https://dashboard.stripe.com/apikeys).
2. Copiá:
   - **Secret key** → `STRIPE_SECRET_KEY`
   - **Publishable key** → `STRIPE_PUBLISHABLE_KEY`
3. Para webhooks (cuando integres confirmación automática):
   - [Webhooks](https://dashboard.stripe.com/webhooks) → Add endpoint
   - URL: `https://{BACKEND_PUBLIC_URL}/api/v1/payments/webhooks/stripe` *(endpoint previsto para integración)*
   - Eventos recomendados: `checkout.session.completed`, `payment_intent.succeeded`
   - Signing secret → `STRIPE_WEBHOOK_SECRET`

### 5.2 Variables de entorno

```env
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

### 5.3 Considerado “configurado”

El backend marca Stripe como `configured: true` en `GET /payments/config` cuando existen:

- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`

> **Estado actual del código:** las credenciales activan el proveedor, pero `StripePaymentProvider.create_checkout_link` aún lanza `NotImplementedError` hasta completar la integración con `stripe.checkout.Session.create`. Mientras tanto, si hay credenciales pero la API no está implementada, el sistema usa el **link local** `/pagar/{token}` como fallback.

---

## 6. Paso 3 — Configurar Authorize.net

### 6.1 Credenciales en el Merchant Interface

1. Iniciá sesión en [Authorize.net](https://account.authorize.net/).
2. **Account → Settings → API Credentials & Keys**
3. Copiá:
   - **API Login ID** → `AUTHORIZE_API_LOGIN_ID`
   - **Transaction Key** → `AUTHORIZE_TRANSACTION_KEY`
4. **Signature Key** (para webhooks) → `AUTHORIZE_SIGNATURE_KEY`

### 6.2 Variables de entorno

```env
AUTHORIZE_API_LOGIN_ID=tu_api_login_id
AUTHORIZE_TRANSACTION_KEY=tu_transaction_key
AUTHORIZE_SIGNATURE_KEY=tu_signature_key
AUTHORIZE_ENV=sandbox
```

| `AUTHORIZE_ENV` | Uso |
|-----------------|-----|
| `sandbox` | Pruebas en entorno de desarrollo Authorize.net |
| `production` | Pagos reales |

### 6.3 Considerado “configurado”

El backend marca Authorize.net como `configured: true` cuando existen:

- `AUTHORIZE_API_LOGIN_ID`
- `AUTHORIZE_TRANSACTION_KEY`

> **Estado actual del código:** igual que Stripe, `AuthorizePaymentProvider.create_checkout_link` está preparado pero pendiente de integración (Accept Hosted / payment links). Sin implementación completa, se usa el fallback local `/pagar/{token}`.

---

## 7. Paso 4 — Verificar la integración

### 1. Estado de configuración (solo lectura)

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/payments/config
```

Respuesta esperada:

```json
{
  "payments_enabled": true,
  "default_provider": "stripe",
  "stub_mode": true,
  "providers": [
    { "provider": "stripe", "configured": false, "label": "Stripe" },
    { "provider": "authorize", "configured": false, "label": "Authorize.net" }
  ]
}
```

- `stub_mode: true` → ningún proveedor tiene credenciales completas **o** la integración real aún no está activa.
- `stub_mode: false` → al menos un proveedor está configurado y listo para checkout real (cuando se implemente).

### 2. Crear un link de pago

```bash
curl -X POST http://localhost:8000/api/v1/payments/links \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_first_name": "Juan",
    "customer_last_name": "Pérez",
    "customer_email": "juan@ejemplo.com",
    "customer_phone": "1131432490",
    "amount": 150.00,
    "currency": "USD",
    "provider": "stripe",
    "description": "Alta de servicio"
  }'
```

### 3. Prueba desde la UI

1. Login como `vendedor@epoint.com` o `admin@epoint.com`.
2. Andá a **Pagos** (`/pagos`).
3. Completá el formulario → **Generar link** (se copia al portapapeles).
4. Abrí el link en otra ventana/incógnito.
5. En modo stub, usá **Simular pago**.
6. Volvé como vendedor → notificación → **Registrar cliente**.

---

## 8. Modo stub (sin credenciales)

Si **no** configurás Stripe ni Authorize.net:

| Comportamiento | Detalle |
|----------------|---------|
| `stub_mode` | `true` |
| URL del link | `{FRONTEND_URL}/pagar/{token}` |
| Pago del cliente | Botón **Simular pago** → `POST /payments/public/{token}/complete` |
| Checkout externo | No disponible |

Ideal para desarrollo local y pruebas de flujo antes de tener cuentas de los proveedores.

Cuando agregues credenciales y completes la integración en los providers:

- El link apuntará al checkout de Stripe o Authorize.net.
- `POST /payments/public/{token}/complete` devolverá **400** (“El pago debe completarse en el checkout del proveedor”).
- La confirmación vendrá por webhook del proveedor *(por implementar)*.

---

## 9. Uso en la aplicación

### Vista `/pagos` (ADMIN y SALES_REP)

La interfaz es **idéntica** para administrador y vendedor:

| Sección | Descripción |
|---------|-------------|
| **Nuevo link de pago** | Datos del cliente, monto, proveedor, descripción opcional |
| **Historial** | Links creados con estado, URL, acciones |

**Diferencia en datos (no en UI):**

- `SALES_REP` ve solo los links que él creó.
- `ADMIN` ve todos los links del sistema.

### Página pública `/pagar/{token}`

Sin autenticación. Muestra resumen del cobro y redirige al checkout (o simulación en stub).

### Registrar cliente tras el pago

Solo cuando el link está en estado `paid` y aún no tiene `client_id`:

1. Clic en **Registrar cliente** en la fila del link.
2. Elegir comercio y origen.
3. Se crea el cliente en el CRM con los datos del link.

---

## 10. Despliegue en Heroku

En la app **backend** (`dev-epoint-crm-backend` o producción):

```bash
heroku config:set PAYMENTS_ENABLED=true -a dev-epoint-crm-backend
heroku config:set PAYMENTS_DEFAULT_PROVIDER=stripe -a dev-epoint-crm-backend
heroku config:set FRONTEND_URL=https://tu-frontend.herokuapp.com -a dev-epoint-crm-backend
heroku config:set STRIPE_SECRET_KEY=sk_test_... -a dev-epoint-crm-backend
heroku config:set STRIPE_PUBLISHABLE_KEY=pk_test_... -a dev-epoint-crm-backend
heroku config:set STRIPE_WEBHOOK_SECRET=whsec_... -a dev-epoint-crm-backend
# Authorize.net (opcional)
heroku config:set AUTHORIZE_API_LOGIN_ID=... -a dev-epoint-crm-backend
heroku config:set AUTHORIZE_TRANSACTION_KEY=... -a dev-epoint-crm-backend
heroku config:set AUTHORIZE_SIGNATURE_KEY=... -a dev-epoint-crm-backend
heroku config:set AUTHORIZE_ENV=sandbox -a dev-epoint-crm-backend
```

Checklist post-deploy:

1. `alembic upgrade head` (migración 019).
2. `python scripts/seed.py` (permisos `payments:*`).
3. Verificar `GET /payments/config` con token de vendedor.
4. Probar flujo completo en `/pagos`.

---

## 11. API REST

Prefijo: `/api/v1/payments`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| `GET` | `/config` | Staff (`payments:read`) | Estado de proveedores (solo lectura) |
| `GET` | `/links` | Staff | Listar links (`?created_by_user_id=` solo admin) |
| `POST` | `/links` | Staff (`payments:create`) | Crear link de pago |
| `POST` | `/links/{id}/cancel` | Staff | Cancelar link pendiente |
| `POST` | `/links/{id}/register-client` | Staff | Alta de cliente post-pago |
| `GET` | `/public/{token}` | Público | Datos del cobro para la página `/pagar` |
| `POST` | `/public/{token}/complete` | Público | Simular pago (solo `stub_mode`) |

### Permisos (seed)

| Permiso | Rol típico |
|---------|------------|
| `payments:read` | ADMIN, SALES_REP |
| `payments:create` | ADMIN, SALES_REP |
| `payments:manage` | ADMIN *(reservado; configuración ya no usa UI)* |

---

## 12. Arquitectura de archivos

### Backend

```
backend/app/
├── api/v1/payments.py              # Endpoints REST
├── core/config.py                  # PAYMENTS_*, STRIPE_*, AUTHORIZE_*
├── models/payment_link.py
├── models/payment_settings.py      # Tabla legacy (no usada para config UI)
├── schemas/payment.py
└── services/payments/
    ├── service.py                  # Lógica principal
    ├── stripe_provider.py          # Integración Stripe (pendiente)
    └── authorize_provider.py       # Integración Authorize.net (pendiente)
```

### Frontend

```
frontend/src/features/payments/
├── components/
│   ├── PagosPage.tsx               # Vista staff (ADMIN = SALES_REP)
│   ├── PaymentLinkForm.tsx
│   ├── PaymentLinkList.tsx
│   ├── RegisterClientFromPaymentModal.tsx
│   └── PublicPaymentPage.tsx
├── hooks/usePayments.ts
└── types.ts
```

Rutas:

- `app/(dashboard)/pagos/page.tsx`
- `app/pagar/[token]/page.tsx`

---

## 13. Solución de problemas

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| No aparece **Pagos** en el menú | Rol sin acceso | Solo `ADMIN` y `SALES_REP` |
| `403` al crear link | Sin permiso `payments:create` | Ejecutar `python scripts/seed.py` |
| `Los pagos están deshabilitados` | `PAYMENTS_ENABLED=false` | Cambiar variable y reiniciar backend |
| Link apunta a `localhost` en Heroku | Falta `FRONTEND_URL` | Configurar URL pública del frontend |
| `stub_mode: true` con claves Stripe | Integración checkout no implementada aún | Normal hasta completar providers |
| Cliente no puede pagar | Link cancelado o ya pagado | Crear nuevo link |
| No llega notificación | Usuario creador inactivo | Verificar usuario vendedor activo |
| `PATCH /payments/config` → 404 | Endpoint eliminado | Configurar solo vía `.env` / Heroku |

---

## Próximos pasos (integración real)

1. Implementar `StripePaymentProvider.create_checkout_link` con `stripe.checkout.Session`.
2. Implementar `AuthorizePaymentProvider` con Accept Hosted o Payment Links.
3. Agregar webhooks para marcar links como `paid` automáticamente.
4. Deshabilitar `POST /public/{token}/complete` cuando `stub_mode` sea `false`.

Documentación relacionada: [DOCUSIGN_SETUP.md](./DOCUSIGN_SETUP.md) (mismo patrón de configuración por entorno).
