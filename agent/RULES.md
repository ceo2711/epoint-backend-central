# Reglas — Backend ePoint CRM

Obligatorias para cualquier agente que modifique este repo.

## Arquitectura

1. Rutas delgadas en `api/v1/` → lógica en `services/` → persistencia en `models/`.
2. Schemas Pydantic en `schemas/`. No mezclar I/O HTTP dentro de models.
3. Background nuevo: usar `workers/enqueue.py` (hilos). **No** asumir Celery/Redis.

## Seguridad y multi-tenant

4. Respetar `sede_scope` y header `X-Merchant-Id`. Fuera de alcance → **404**, no 403.
5. Permisos vía `deps.py`. `clients:delete` y CRUD sedes/merchants/sources → solo `ADMIN`.
6. Datos sensibles (SSN, TOTP, credenciales vault) siempre cifrados con `ENCRYPTION_KEY`.
7. No loguear ni devolver secrets, tokens crudos ni SSN en claro.

## Migraciones y datos

8. No usar `alembic revision --autogenerate` a ciegas: hay cadena `001`–`045` (head = `045_course_catalog`). Extender versions a mano con cuidado.
9. En Heroku el `release` corre `alembic upgrade head`. Toda migración debe ser reversible o al menos segura en prod.
10. No commitear `.env`. Config Heroku con `scripts/push_heroku_backend_config.py`.

## Dominio documentos

11. Antes de notificar rechazo / próximo a vencer, consultar `document_needs_client_action`: si otra alternativa de la misma categoría ya cubre el requisito, **no** avisar.
12. `REPLACEMENT_STATUSES` = `RECHAZADO` | `PROXIMO_A_VENCER`.

## Chatbot y notificaciones

13. El chatbot solo confirma acciones que realmente ejecutó.
14. En local, `NOTIFICATIONS_DRY_RUN=true` por defecto; no “arreglar” forzando envíos reales sin pedirlo.

## API / errores

15. Mensajes de API orientados a usuario en español (`validation_errors.py` humaniza 422).
16. En 500, detalle técnico solo si `DEBUG`; si no, mensaje genérico.

## Git y deploy

17. Este repo es independiente del frontend/mobile. Deploy solo desde esta carpeta.
18. Apps reales: dev `dev-epoint-crm-backend` (`heroku`), prod `epoint-crm-backend` (`heroku-prod`). No inventar nombres.
19. Push típico a GitHub: `git push origin HEAD`. Deploy Heroku solo si lo piden: `git push heroku HEAD:main` (dev) o `heroku-prod` (prod).
20. Commits en español, enfocados en el *porqué*; no incluir secrets.
21. Cursos/mentorías se desarrollan en `feature/cursos-mentorias`. **Nunca** commitear ni desplegar ese trabajo sobre `release/1.0.0`.

## Tests

22. Si tocás reglas de documentos, pagos, auth o entitlements, agregá o actualizá tests en `tests/unit/` (o API smoke).
23. Corré `pytest` antes de dar por cerrado un cambio de lógica de negocio.

## Productos y checkout

24. Entitlements combinables (`CREDIT` / `COURSE` / `MENTORSHIP`). Un cliente, un user `CLIENT`. No crear un segundo cliente por comprar otro producto del mismo email.
25. `ClientStatus` no representa “qué compró”. `SIN_ASESORIA` es solo educativo. Grant `CREDIT` arranca onboarding (`ensure_credit_track`).
26. Payment links educativos (`product_code` COURSE/MENTORSHIP) **no** pasan por `try_auto_convert`.
27. Checkout público no lleva JWT. Actor = `system@epoint.com`; merchant = `epoint-credits`; source = `LANDING`.
28. Videos de lección: MIME `video/mp4` con upload firmado (Bucketeer). No reutilizar `ALLOWED_MIME_TYPES` de documentos.
29. Permiso de catálogo/upload: `courses:manage`. Player portal: `GET /portal/courses` (exige entitlement COURSE).
30. No meter `appreview@epoint.com` ni otras cuentas de review en seeds de demo de cursos. La excepción 2FA es solo App Store.
