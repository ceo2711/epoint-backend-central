#!/usr/bin/env python3
"""Sube variables de backend/.env a Heroku (sin commitear secretos).

Uso:
  python scripts/push_heroku_backend_config.py              # app de desarrollo
  python scripts/push_heroku_backend_config.py --app prod   # app de producción
  python scripts/push_heroku_backend_config.py --app epoint-crm-backend
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
HEROKU_BIN = shutil.which("heroku") or r"C:\Program Files\heroku\bin\heroku.cmd"

APP_ALIASES = {
    "dev": "dev-epoint-crm-backend",
    "prod": "epoint-crm-backend",
}

# Overrides por entorno (URLs y flags seguros). No pisan DATABASE_URL / BUCKETEER_*.
DEV_OVERRIDES: dict[str, str] = {
    "APP_ENV": "production",
    "DEBUG": "false",
    "FRONTEND_URL": "https://dev-epoint-crm-frontend-4985af85e0a2.herokuapp.com",
    "CORS_ORIGINS": "https://dev-epoint-crm-frontend-4985af85e0a2.herokuapp.com",
    "BACKEND_PUBLIC_URL": "https://dev-epoint-crm-backend-3807e7e86dca.herokuapp.com",
    "S3_STORAGE_PREFIX": "dev/",
    "DOCUSIGN_DEFAULT_TEMPLATE_ROLE_NAME": "Cliente",
}

PROD_OVERRIDES: dict[str, str] = {
    "APP_ENV": "production",
    "DEBUG": "false",
    "FRONTEND_URL": "https://epoint-crm-frontend-8a88c1924ab8.herokuapp.com",
    "CORS_ORIGINS": "https://epoint-crm-frontend-8a88c1924ab8.herokuapp.com",
    "BACKEND_PUBLIC_URL": "https://epoint-crm-backend-7d70ac333373.herokuapp.com",
    "S3_STORAGE_PREFIX": "prod/",
    "S3_USE_SSL": "true",
    "S3_ENDPOINT_URL": "",
    "DOCUSIGN_DEFAULT_TEMPLATE_ROLE_NAME": "Cliente",
    # Soft-launch seguro hasta validar webhooks/pagos reales:
    "PAYMENT_TEST": "true",
    "AUTHORIZE_ENV": "sandbox",
    "PAYPAL_ENV": "sandbox",
    # En prod no redirigir emails a sandbox; dejar vacío / unset
    "EMAIL_DEV_REDIRECT_TO": "",
    # Recordatorios: 1 vez cada 3 meses (2160 h) hasta definir la regularidad
    "PAYMENT_REMINDER_COOLDOWN_HOURS": "2160",
    "CONTRACT_REMINDER_COOLDOWN_HOURS": "2160",
    "BOARD_REMINDER_COOLDOWN_HOURS": "2160",
    "ONBOARDING_REMINDER_COOLDOWN_HOURS": "2160",
}

# Nunca subir desde .env local (Heroku addons o deben ser secretos nuevos de prod).
SKIP_ALWAYS = {
    "DATABASE_URL",
    "REDIS_URL",
    "BUCKETEER_AWS_ACCESS_KEY_ID",
    "BUCKETEER_AWS_SECRET_ACCESS_KEY",
    "BUCKETEER_AWS_REGION",
    "BUCKETEER_BUCKET_NAME",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "S3_BUCKET_NAME",
    "S3_ENDPOINT_URL",
}

# En producción: regenerar estos en Heroku (no reutilizar los de local/dev).
PROD_SKIP_SECRETS = {
    "JWT_SECRET_KEY",
    "ENCRYPTION_KEY",
}


def parse_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(path)
    content = path.read_text(encoding="utf-8")
    for match in re.finditer(
        r'^([A-Z][A-Z0-9_]*)[ \t]*=[ \t]*("(?:[^"\\]|\\.|\\n)*"|[^\n#]+)',
        content,
        re.MULTILINE,
    ):
        key, raw = match.group(1), match.group(2).strip()
        if raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]
            raw = raw.replace("\\n", "\n").replace('\\"', '"')
        data[key] = raw

    for match in re.finditer(
        r'^([A-Z][A-Z0-9_]*)[ \t]*=[ \t]*"([\s\S]*?)"\s*$',
        content,
        re.MULTILINE,
    ):
        key, raw = match.group(1), match.group(2)
        if "\n" in raw or key not in data:
            data[key] = raw
    return data


def pem_to_heroku(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\n", "\\n")


def resolve_app(raw: str) -> str:
    return APP_ALIASES.get(raw, raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Push backend/.env config to Heroku")
    parser.add_argument(
        "--app",
        default="dev",
        help="Alias (dev|prod) o nombre exacto de la app Heroku",
    )
    parser.add_argument(
        "--include-secrets",
        action="store_true",
        help="En prod, también subir JWT_SECRET_KEY/ENCRYPTION_KEY desde .env (no recomendado)",
    )
    args = parser.parse_args()
    heroku_app = resolve_app(args.app)
    is_prod = heroku_app == APP_ALIASES["prod"] or args.app == "prod"

    env = parse_env(BACKEND_ENV)
    overrides = PROD_OVERRIDES if is_prod else DEV_OVERRIDES
    env.update(overrides)

    if "DOCUSIGN_PRIVATE_KEY" in env:
        env["DOCUSIGN_PRIVATE_KEY"] = pem_to_heroku(env["DOCUSIGN_PRIVATE_KEY"])

    skip = set(SKIP_ALWAYS)
    if is_prod and not args.include_secrets:
        skip |= PROD_SKIP_SECRETS

    empty_keys = sorted(k for k, v in env.items() if k not in skip and not str(v).strip())
    if empty_keys:
        print(f"Quitando {len(empty_keys)} vars vacías de {heroku_app}: {', '.join(empty_keys)}")
        unset = [HEROKU_BIN, "config:unset", *empty_keys, "-a", heroku_app]
        result = subprocess.run(unset, check=False)
        if result.returncode not in (0, 1):
            return result.returncode

    items = [(k, v) for k, v in env.items() if k not in skip and str(v).strip()]
    batch_size = 8
    print(f"Subiendo {len(items)} variables a {heroku_app}...")
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        pairs = [f"{k}={v}" for k, v in batch]
        cmd = [HEROKU_BIN, "config:set", *pairs, "-a", heroku_app]
        result = subprocess.run(cmd, check=False)
        if result.returncode not in (0, 1):
            print(f"Error en batch {i // batch_size + 1}", file=sys.stderr)
            return result.returncode
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
