# ePoint CRM — Backend (FastAPI)

API REST del CRM. Diseñada para desplegarse como app Heroku independiente del frontend.

## Requisitos

- Python 3.12+
- Docker y Docker Compose (Postgres, Redis, MinIO local)

## Inicio rápido (local)

```bash
# 1. Infraestructura
docker compose up -d

# 2. Entorno virtual
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Variables de entorno
cp .env.example .env
# Editar .env — mínimo: DATABASE_URL, JWT_SECRET_KEY, GEMINI_API_KEY

# 4. Migraciones y datos iniciales
alembic revision --autogenerate -m "initial"
alembic upgrade head
python scripts/seed.py

# 5. Arrancar API (incluye recordatorios automáticos y verificación IA en background)
uvicorn app.main:app --reload --port 8000
```

- API: http://localhost:8000/api/v1/health
- Docs: http://localhost:8000/docs
- MinIO console: http://localhost:9001 (minioadmin / minioadmin)

**Usuario admin por defecto:** `admin@epoint.com` / `Admin123!`

## Variables de entorno

Ver `.env.example`. Las más importantes:

| Variable | Descripción |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL |
| `JWT_SECRET_KEY` | Secreto para tokens |
| `ENCRYPTION_KEY` | Cifrado SSN/credenciales (32 bytes base64) |
| `GEMINI_API_KEY` | API key de Google AI (Gemini Flash 2.5) |
| `REDIS_URL` | Opcional (solo si usás Celery legacy manualmente) |
| `ONBOARDING_REMINDER_INTERVAL_MINUTES` | Recordatorios automáticos dentro de la API (0 = off; ej. `120` cada 2 h). También disponible el botón manual en Clientes |
| `AWS_*` / `BUCKETEER_*` | Almacenamiento S3 |

## Recordatorios y tareas en background

Todo corre **dentro del proceso de la API** (hilos daemon):

- **Recordatorios de onboarding:** scheduler si `ONBOARDING_REMINDER_INTERVAL_MINUTES` > 0 (primer ciclo al arrancar; luego cada N min). Un solo ciclo a la vez entre procesos (lock en Postgres).
- **Verificación IA de documentos/adjuntos:** se lanza en background al subir archivos
- **Disparo manual:** botón «Enviar recordatorios» en Clientes (admin / onboarding).

No hace falta Celery, Redis ni terminales extra para desarrollo ni Heroku.

En Heroku: solo el dyno `web`. Si escalás a varios dynos web, el lock de Postgres evita ciclos duplicados; igualmente conviene 1 dyno web o intervalo 0 + botón manual.

## Heroku

```bash
heroku create epoint-crm-api
heroku addons:create heroku-postgresql:mini
heroku addons:create heroku-redis:mini
heroku addons:create bucketeer:hobbyist
# Config vars: JWT_SECRET_KEY, ENCRYPTION_KEY, GEMINI_API_KEY, CORS_ORIGINS
git push heroku main
```

El `Procfile` define `web` (API con scheduler integrado) y `release` (migraciones).

```bash
heroku config:set ONBOARDING_REMINDER_INTERVAL_MINUTES=120 -a tu-app-backend
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Estructura

```
app/
├── api/
│   ├── deps.py         # Dependencias FastAPI (sesión DB, permisos)
│   └── v1/             # Endpoints REST (versión 1)
├── core/               # Config, auth, DB, cifrado
├── models/             # Tablas SQLAlchemy
├── schemas/            # Validación Pydantic (entrada/salida)
├── services/           # Lógica de negocio
└── workers/            # Tareas en background (Celery)
migrations/             # Cambios a la base de datos (Alembic)
```
