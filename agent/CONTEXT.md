# Contexto — Backend ePoint CRM

Repo git independiente. App Heroku: **`dev-epoint-crm-backend`**.  
URL: `https://dev-epoint-crm-backend-3807e7e86dca.herokuapp.com`

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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 5
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
  constants/                # kanban columns, default cards
migrations/versions/        # 001…031 — no autogenerate a la ligera
scripts/                    # seed, push_heroku_backend_config.py, qa_*
tests/{unit,api}/
```

### Routers (`/api/v1`)

`health`, `auth`, `advisors`, `users`, `sub_sellers`, `areas`, `sedes`, `merchants`, `sources`, `influencers`, `roles`, `notifications`, `clients`, `prospects`, `dashboard`, `calendly`, `docusign`, `payments`, `onboarding_reminders`, `portal`, `documents`, `boards`, `chatbot`

## Multi-tenant y auth

- Roles: `ADMIN`, `BRANCH_MANAGER`, `AREA_LEADER`, `SALES_REP`, `ONBOARDING_MANAGER`, `ADVISOR`, `CLIENT`
- Permisos `recurso:acción` vía `require_permissions` en `api/deps.py`
- Aislamiento por **sede** (`sede_scope.py`): fuera de alcance → **404**
- Staff multi-comercio: header **`X-Merchant-Id`**
- `CLIENT` usa `/portal/*`; no usa merchant context
- 2FA: login → `requires_2fa` + temp token → `POST /auth/2fa/verify`

## Dominios clave

| Dominio | Dónde |
|---------|--------|
| Prospectos → clientes | `services/prospects.py`, `clients.py` |
| Portal | `api/v1/portal.py` |
| Documentos + IA | upload → `enqueue_document_verification`; reglas en `document_requirements.py` |
| Alternativas de docs | Si licencia aprobada, no avisar por green card rechazada (`document_needs_client_action`) |
| Board Kanban | `services/boards.py`, `constants/kanban_columns.py` |
| Pagos | `services/payments/` + webhooks; `PAYMENT_TEST=true` simula cobro con botón Pagar en `/pagar/{token}` |
| Notificaciones | hub + email/WhatsApp/PUSH Expo; `push_device_tokens`; `NOTIFICATIONS_DRY_RUN` |
| Chatbot | acciones reales; no inventar confirmaciones |
| Onboarding reminders | scheduler inline + lock Postgres |

## Deploy Heroku

```bash
git push origin HEAD                    # feature/prospectos u otra rama
git push heroku HEAD:main               # remote: https://git.heroku.com/dev-epoint-crm-backend.git
```

- `Procfile`: `web: uvicorn …` · `release: alembic upgrade head`
- Config: `python scripts/push_heroku_backend_config.py`
- Pareja frontend: `dev-epoint-crm-frontend`

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
