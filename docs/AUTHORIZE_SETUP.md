# Configuración Authorize.net — ePoint CRM

Guía paso a paso para conectar tu cuenta **Authorize.net** (sandbox o producción) con ePoint CRM y generar **links de pago**.

**Rutas en la app:** `/pagos` (staff) · `/pagar/{token}` (cliente)  
**Roles con acceso:** `ADMIN`, `BRANCH_MANAGER`, `SALES_REP`  
**Modelo:** cuenta **única de la empresa** vía variables de entorno del backend (igual que PayPal / DocuSign)

---

## Tabla de contenidos

1. [Resumen](#1-resumen)
2. [Qué vas a configurar en Authorize](#2-qué-vas-a-configurar-en-authorize)
3. [Paso 1 — Cuenta Sandbox (pruebas)](#3-paso-1--cuenta-sandbox-pruebas)
4. [Paso 2 — Obtener API Login ID y Transaction Key](#4-paso-2--obtener-api-login-id-y-transaction-key)
5. [Paso 3 — Signature Key (webhooks, recomendado)](#5-paso-3--signature-key-webhooks-recomendado)
6. [Paso 4 — Variables en el CRM](#6-paso-4--variables-en-el-crm)
7. [Paso 5 — Webhook (recomendado)](#7-paso-5--webhook-recomendado)
8. [Paso 6 — Verificar y probar](#8-paso-6--verificar-y-probar)
9. [Tarjetas de prueba (sandbox)](#9-tarjetas-de-prueba-sandbox)
10. [Pasar a producción](#10-pasar-a-producción)
11. [Límites de la página hospedada](#11-límites-de-la-página-hospedada)
12. [Solución de problemas](#12-solución-de-problemas)

---

## 1. Resumen

| Aspecto | Detalle |
|---------|---------|
| **Producto** | Accept Hosted (página de pago en Authorize.net) |
| **Credenciales** | Solo en el **backend** (`AUTHORIZE_*`) |
| **UI de config en el CRM** | No existe — se configura por `.env` / Heroku |
| **Flujo** | El CRM pide un token → el cliente abre `/pagar/{token}` → el CRM hace POST a Authorize → paga con tarjeta |
| **Datos precargados** | Nombre, apellido, email y teléfono del formulario de Pagos |
| **Confirmación** | Webhook (recomendado) y/o retorno a `/pagar/{token}?paid=1` |

### Sandbox vs producción

| Entorno | `AUTHORIZE_ENV` | API | Página de pago |
|---------|-----------------|-----|----------------|
| **Sandbox** | `sandbox` | `apitest.authorize.net` | `test.authorize.net/payment/payment` |
| **Live** | `production` | `api.authorize.net` | `accept.authorize.net/payment/payment` |

> Usá **sandbox** hasta validar el flujo. Los cobros sandbox no mueven dinero real.

---

## 2. Qué vas a configurar en Authorize

En el panel de Authorize.net necesitás:

1. **API Login ID**
2. **Transaction Key**
3. **Signature Key** (para validar webhooks; recomendado)
4. Un **Webhook** apuntando al backend del CRM (recomendado en Heroku / URL pública)

No hace falta OAuth por vendedor ni variables en el frontend.

---

## 3. Paso 1 — Cuenta Sandbox (pruebas)

1. Entrá a [https://developer.authorize.net](https://developer.authorize.net/) o creá una cuenta de prueba en [sandbox.authorize.net](https://sandbox.authorize.net/).
2. Si todavía no tenés sandbox: en Developer Central pedí / creá una **Sandbox Account**.
3. Iniciá sesión en el **Merchant Interface** del sandbox: [https://sandbox.authorize.net](https://sandbox.authorize.net/).

> La cuenta sandbox es distinta de la cuenta Live. Las keys de una **no** sirven en la otra.

---

## 4. Paso 2 — Obtener API Login ID y Transaction Key

1. En el Merchant Interface (sandbox o live): menú **Account**.
2. Buscá **Settings** → **Security Settings** → **API Credentials & Keys**  
   (a veces aparece como *API Login ID and Transaction Key*).
3. Anotá el **API Login ID** (no cambia salvo que regeneres).
4. Generá una **New Transaction Key**:
   - Elegí *New Transaction Key*
   - Confirmá con la respuesta de seguridad / PIN si te lo pide
   - **Copiá la key de una vez** (no se vuelve a mostrar completa)
5. Esas dos valores van al CRM:

| Campo Authorize | Variable en el CRM |
|-----------------|--------------------|
| API Login ID | `AUTHORIZE_API_LOGIN_ID` |
| Transaction Key | `AUTHORIZE_TRANSACTION_KEY` |

---

## 5. Paso 3 — Signature Key (webhooks, recomendado)

Sirve para firmar/validar notificaciones de pago.

1. En **Account** → **Settings** → **API Credentials & Keys** (o sección **Signature Key**).
2. Generá una **New Signature Key**.
3. Guardala como `AUTHORIZE_SIGNATURE_KEY` en el CRM.

Si todavía no configurás webhook, podés dejarla vacía en local; en staging/producción conviene tenerla.

---

## 6. Paso 4 — Variables en el CRM

En `backend/.env` (local):

```env
PAYMENTS_ENABLED=true
PAYMENTS_DEFAULT_PROVIDER=authorize

AUTHORIZE_API_LOGIN_ID=tu_api_login_id
AUTHORIZE_TRANSACTION_KEY=tu_transaction_key
AUTHORIZE_SIGNATURE_KEY=tu_signature_key
AUTHORIZE_ENV=sandbox

FRONTEND_URL=http://localhost:3000
BACKEND_PUBLIC_URL=http://localhost:8000
```

Reiniciá el backend después de guardar.

### En Heroku (cuando pases a staging)

```bash
heroku config:set AUTHORIZE_API_LOGIN_ID=... -a dev-epoint-crm-backend
heroku config:set AUTHORIZE_TRANSACTION_KEY=... -a dev-epoint-crm-backend
heroku config:set AUTHORIZE_SIGNATURE_KEY=... -a dev-epoint-crm-backend
heroku config:set AUTHORIZE_ENV=sandbox -a dev-epoint-crm-backend
heroku config:set PAYMENTS_ENABLED=true -a dev-epoint-crm-backend
```

También podés usar el script del repo (lee `backend/.env` y sube vars, con overrides de URLs de Heroku):

```bash
cd backend && python scripts/push_heroku_backend_config.py
```

### Cómo saber si quedó bien

Con un usuario staff:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/payments/config
```

Esperado: proveedor `authorize` con `"configured": true`.

En la UI de **Pagos**, el selector debe mostrar **Authorize.net**.

---

## 7. Paso 5 — Webhook (recomendado)

Authorize puede avisar al CRM cuando el pago se completa (útil si el cliente cierra el navegador antes de volver).

1. En Merchant Interface → **Account** → **Webhooks** (o *Notification / Business Settings*).
2. **Add Endpoint** con URL:

```text
https://{BACKEND_PUBLIC_URL}/api/v1/payments/webhooks/authorize
```

Ejemplo Heroku staging:

```text
https://dev-epoint-crm-backend-3807e7e86dca.herokuapp.com/api/v1/payments/webhooks/authorize
```

3. Eventos sugeridos:
   - `net.authorize.payment.authcapture.created`
   - `net.authorize.payment.capture.created`
4. Activá el endpoint.

### Local

Authorize **no** puede llamar a `localhost`. Opciones:

- Probar el retorno del checkout (`/pagar/{token}?paid=1`) sin webhook, o
- Usar un túnel (`ngrok http 8000`) y poner esa URL HTTPS en `BACKEND_PUBLIC_URL` y en el webhook.

---

## 8. Paso 6 — Verificar y probar

1. Login como vendedor o admin.
2. **Pagos** → crear link con proveedor **Authorize.net** (monto chico, ej. `1.00` USD).
3. Abrí el link (debe ser la URL del CRM `/pagar/...`, no pegar a mano una URL larga de Authorize).
4. Completá el pago con una [tarjeta de prueba](#9-tarjetas-de-prueba-sandbox).
5. Confirmá en el CRM que el link pasó a **Pagado** (y, si había prospecto, el historial / estado).

### Cancelar

Desde **Pagos**, cancelá un link **Pendiente**. Si está vinculado a un prospecto, queda registrado en el historial.

---

## 9. Tarjetas de prueba (sandbox)

Usá las tarjetas de prueba de Authorize.net (sandbox), por ejemplo:

| Número | Resultado típico |
|--------|------------------|
| `4111111111111111` | Aprobada (Visa) |
| `5424000000000015` | Aprobada (Mastercard) |

- Fecha: cualquier mes/año **futuro**
- CVV: cualquier 3 dígitos (ej. `123`)
- Dirección / ZIP: cualquier valor válido de prueba

Documentación oficial de prueba: [Authorize.net Testing Guide](https://developer.authorize.net/hello_world/testing_guide.html)

---

## 10. Pasar a producción

1. Cuenta Business Live en [account.authorize.net](https://account.authorize.net/).
2. Generá **API Login ID**, **Transaction Key** y **Signature Key** de **Live** (no reutilices las de sandbox).
3. Variables:

```env
AUTHORIZE_API_LOGIN_ID=...        # Live
AUTHORIZE_TRANSACTION_KEY=...     # Live
AUTHORIZE_SIGNATURE_KEY=...       # Live
AUTHORIZE_ENV=production
FRONTEND_URL=https://tu-frontend-produccion
BACKEND_PUBLIC_URL=https://tu-backend-produccion
```

4. Webhook Live apuntando al backend de producción.
5. Probá un cobro mínimo real y confirmá en el Merchant Interface.

> No mezcles keys sandbox con `AUTHORIZE_ENV=production` (ni al revés).

---

## 11. Límites de la página hospedada

Accept Hosted es una página de **Authorize**, no del CRM:

| Se puede | No se puede |
|----------|-------------|
| Precargar nombre, apellido, email, teléfono | Subir el **logo** de la empresa en esa ventana |
| Mostrar nombre del comercio y color de acento | Rediseñar por completo la UI de Authorize |
| Ocultar pago con cuenta bancaria (USA) | Forzar solo “datos de tarjeta” sin billing address |

Si más adelante necesitás branding total (logo ePoint en la pantalla de tarjeta), habría que evaluar un checkout embebido / otra integración.

---

## 12. Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---------|----------------|-----------|
| Authorize no aparece / `configured: false` | Faltan Login ID o Transaction Key | Revisar `.env` y reiniciar API |
| `Missing or invalid token` | Abriste una URL vieja `?token=...` en GET | Generá un **link nuevo** y abrí `/pagar/{token}` del CRM |
| Error al crear link (502) | Keys inválidas o sandbox/live mezclados | Verificar `AUTHORIZE_ENV` y keys del mismo entorno |
| Authorize rechaza `localhost` en return URL | Limitación del sandbox | El CRM convierte `localhost` → `127.0.0.1` automáticamente |
| Paga pero el CRM sigue en Pendiente | Sin webhook y falló el retorno | Configurá webhook; reabrí `/pagar/{token}?paid=1` |
| Webhook no llega en local | `localhost` no es público | Usá ngrok o probá en Heroku |

---

## Checklist rápido

- [ ] Cuenta sandbox Authorize.net
- [ ] API Login ID + Transaction Key en `backend/.env`
- [ ] `AUTHORIZE_ENV=sandbox`
- [ ] Backend reiniciado → `/payments/config` muestra Authorize configurado
- [ ] Crear link desde `/pagos`
- [ ] Pagar con tarjeta de prueba
- [ ] Ver estado **Pagado**
- [ ] (Recomendado) Webhook + `BACKEND_PUBLIC_URL` público
- [ ] (Producción) Keys Live + `AUTHORIZE_ENV=production`

Cuando eso esté verde, Authorize.net queda listo para generar links de pago en ePoint CRM.

Documentación relacionada:

- [PAYMENTS_INTEGRATION.md](./PAYMENTS_INTEGRATION.md) — overview Authorize + PayPal
- [PAYPAL_SETUP.md](./PAYPAL_SETUP.md) — guía equivalente de PayPal
