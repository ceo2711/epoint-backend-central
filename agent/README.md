# Agente especializado — Backend ePoint CRM

Esta carpeta viaja con el repositorio. Si clonás solo el backend en otra PC, el agente de Cursor tiene todo el contexto acá.

## Archivos

| Archivo | Uso |
|---------|-----|
| [`CONTEXT.md`](./CONTEXT.md) | Stack, arquitectura, dominios, paths, deploy |
| [`RULES.md`](./RULES.md) | Reglas obligatorias al modificar código |

## Cómo usarlo en Cursor

1. Abrí la carpeta del repo (`epoint-central-backend` o `backend/`) como workspace.
2. El `AGENTS.md` de la raíz apunta acá: Cursor lo carga al iniciar.
3. Si el chat no tiene contexto, pedile: *“Leé agent/CONTEXT.md y agent/RULES.md”*.

## Rama de trabajo

Cursos/mentorías: `feature/cursos-mentorias`. Store/prod: `release/1.0.0`. Ciclo 2: `release/2.0.0`.

## Repo hermano

- Frontend: `epoint-frontend-central` → Heroku `dev-epoint-crm-frontend` / `epoint-crm-frontend`
- Mobile: `epoint-mobile-central` (Expo; sin Heroku)
- Landing: `AlexisGuanique/epoint-credits` → Heroku `epoint-credits` (llama `POST /api/v1/public/checkout`)
- Este backend: GitHub `ceo2711/epoint-backend-central` → Heroku `dev-epoint-crm-backend` / `epoint-crm-backend`
