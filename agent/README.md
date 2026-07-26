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

## Repo hermano

- Frontend: `epoint-central-frontend` → Heroku `dev-epoint-crm-frontend`
- Mobile: `epoint-central-mobile` (Expo; sin Heroku)
- Este backend: GitHub `epoint-central-backend` → Heroku `dev-epoint-crm-backend`
