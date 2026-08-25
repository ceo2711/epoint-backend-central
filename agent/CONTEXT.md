# Contexto — Backend ePoint CRM

Repo git independiente: `https://github.com/ceo2711/epoint-backend-central.git`

| Ambiente | App Heroku | Remote git | URL |
|----------|------------|------------|-----|
| Dev | `dev-epoint-crm-backend` | `heroku` | `https://dev-epoint-crm-backend-3807e7e86dca.herokuapp.com` |
| Prod | `epoint-crm-backend` | `heroku-prod` | `https://epoint-crm-backend-7d70ac333373.herokuapp.com` |

Pareja frontend: `dev-epoint-crm-frontend` / `epoint-crm-frontend`.

## Estado actual (ago 2026)

- Trabajo de **cursos/mentorías** vive en `feature/cursos-mentorias`. **No** mezclar ni desplegar en `release/1.0.0` (esa rama es el CRM de store / prod actual).
- Convención: **prod store** = `release/1.0.0`; **ciclo 2 / dev** = `release/2.0.0`. Mergear cursos a 2.0.0 cuando esté listo, no a 1.0.0.
- Un `Client` + user `CLIENT` puede tener productos **combinables**: `CREDIT` | `COURSE` | `MENTORSHIP` (`client_entitlements`).
- `ClientStatus` es solo el pipeline de **asesoría**. Sin `CREDIT` no hay onboarding ni tablero. Status `SIN_ASESORIA` = portal educativo sin asesoría.
- Dos puertas de alta:
  1. **Vendedor:** prospecto → DocuSign → pago → grant `CREDIT`. Si el email ya existe (compró curso/mentoría), **merge**: se suma `CREDIT` y arranca onboarding (`ensure_credit_track`).
  2. **Landing epoint-credits:** stepper → `POST /api/v1/public/checkout` → `/pagar/{token}`. Al pagar, grant `COURSE` o `MENTORSHIP`. Alta nueva manda bienvenida `_send_client_portal_welcome`. Educación **no** pasa por `try_auto_convert`.
- Cursos: catálogo sembrado desde `app/constants/course_catalog.json` (12 módulos / 36 lecciones, migración `045`). El asesor sube MP4 firmado a Bucketeer; el cliente reproduce en `GET /portal/courses`. Permiso `courses:manage`.
- Checkout landing usa usuario sistema `system@epoint.com`, merchant `epoint-credits`, source `LANDING`.
- App Store Review: `APP_REVIEW_EMAILS` default `appreview@epoint.com` — sin 2FA ni `must_change_password`. No ampliar la lista a cuentas reales.
- CORS local incluye `localhost:3001` (landing). En Heroku hay que sumar el origen de la landing al `CORS_ORIGINS` si el checkout público corre contra ese backend.
- Mentoría Calendly **pendiente**. No hay IAP: los cobros son payment links del CRM (Authorize.net / PayPal).

## Stack

- Python 3.12 · FastAPI 0.115 · Uvicorn · SQLAlchemy 2 · Alembic · Postgres 16
- Auth: JWT + Argon2 + TOTP 2FA · Storage: S3/MinIO/Bucketeer
- IA docs: Gemini 2.5 Flash (`google-genai`) · Email: Resend · WhatsApp: Twilio
- Pagos: Authorize.net (default), PayPal; Stripe legacy
- Background: **hilos en la API** (`workers/enqueue.py`). Celery/Redis = legacy, no requerido

## Arranque local

```bash
docker compose up -d
python -m venv .venv && source .venv/bin/activate   # Win: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # DATABASE_URL, JWT_SECRET_KEY, GEMINI_API_KEY…
alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 15
```

- Docs: `http://localhost:8000/docs` · Health: `/api/v1/health`
- Admin seed: `admin@epoint.com` / `Admin123!`
- Celery **no** hace falta para el flujo normal

## Estructura

```
app/
  main.py
  api/deps.py + api/v1/     # routers REST bajo /api/v1
  core/                     # config, database, security, encryption
  models/ schemas/ serializers/
  services/                 # lógica de negocio
  workers/                  # enqueue (hilos), document_verification, reminders
  constants/                # kanban columns, default cards, course_catalog.json
migrations/versions/        # cadena a mano; head actual 045 — no autogenerate a la ligera
scripts/                    # seed, push_heroku_backend_config.py, qa_*
tests/{unit,api}/
```

### Routers (`/api/v1`)

`health`, `branding`, `auth`, `advisors`, `users`, `sub_sellers`, `areas`, `sedes`, `merchants`, `sources`, `influencers`, `roles`, `notifications`, `clients`, `prospects`, `dashboard`, `calendly`, `docusign`, `payments`, `public` (checkout), `onboarding_reminders`, `portal`, `courses`, `documents`, `boards`, `chatbot`

Checkout público: `GET /public/products`, `POST /public/checkout` (sin JWT).  
Cursos staff: `/courses` (`courses:manage`). Player cliente: `/portal/courses`.

## Multi-tenant y auth

- Roles: `ADMIN`, `BRANCH_MANAGER`, `AREA_LEADER`, `SALES_REP`, `SUB_SELLER`, `ADVISOR`, `CLIENT`
- Permisos `recurso:acción` vía `require_permissions` en `api/deps.py`
- Aislamiento por **sede** (`sede_scope.py`): fuera de alcance → **404**
- Staff multi-comercio: header **`X-Merchant-Id`**
- `CLIENT` usa `/portal/*`; no usa merchant context
- 2FA: login → `requires_2fa` + temp token → `POST /auth/2fa/verify`
- Excepción: `is_app_review_email` (`app/core/app_review.py`) saltea TOTP y must_change_password
- `/auth/me` incluye `entitlements: { credit, course, mentorship }`

## Dominios clave

| Dominio | Dónde |
|---------|--------|
| Prospectos → clientes | `services/prospects.py`, `clients.py` |
| Portal | `api/v1/portal.py` |
| Documentos + IA | upload → `enqueue_document_verification`; reglas en `document_requirements.py` |
| Alternativas de docs | Si licencia aprobada, no avisar por green card rechazada (`document_needs_client_action`) |
| Board Kanban | `services/boards.py`, `constants/kanban_columns.py` |
| Pagos | `services/payments/` + webhooks; `PAYMENT_TEST=true` simula cobro con botón Pagar en `/pagar/{token}`. `product_code` en el link. Educación no auto-convierte. |
| Entitlements | `services/entitlements.py` — grant/merge CREDIT/COURSE/MENTORSHIP |
| Cursos | `services/courses.py` + `constants/course_catalog.json`; upload firmado `video/mp4` (MIME aparte de docs) |
| Checkout landing | `api/v1/public_checkout.py` |
| Notificaciones | hub + email/WhatsApp/PUSH Expo; `push_device_tokens`; `NOTIFICATIONS_DRY_RUN` |
| Chatbot | acciones reales; no inventar confirmaciones |
| Onboarding reminders | scheduler inline + lock Postgres |

## Deploy Heroku

```bash
git push origin HEAD                         # GitHub (rama actual)
git push heroku HEAD:main                    # SOLO dev
# git push heroku-prod HEAD:main             # SOLO si se pide prod explícito
```

- `Procfile`: `web: uvicorn …` · `release: alembic upgrade head`
- Config: `python scripts/push_heroku_backend_config.py`
- **No desplegar** `feature/cursos-mentorias` a prod/`release/1.0.0` salvo pedido explícito.
- Tras deploy, `alembic upgrade head` corre en el release phase (migraciones 044 y 045).

## Config crítica

- `.env` / `.env.example` (nunca committear `.env`)
- `app/core/config.py` — normaliza `postgres://` → `postgresql://`; aliases Bucketeer
- Obligatorias: `DATABASE_URL`, `JWT_SECRET_KEY`
- Sensibles: `ENCRYPTION_KEY`, `GEMINI_API_KEY`, pagos, DocuSign, Twilio, Resend, `BACKEND_PUBLIC_URL`

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Mayormente `tests/unit/`; API smoke en `tests/api/`.
