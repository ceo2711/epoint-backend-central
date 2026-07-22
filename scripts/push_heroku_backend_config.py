#!/usr/bin/env python3
"""Sube variables de backend/.env a Heroku (sin commitear secretos)."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
HEROKU_APP = "dev-epoint-crm-backend"
HEROKU_BIN = shutil.which("heroku") or r"C:\Program Files\heroku\bin\heroku.cmd"

# Overrides para producción en Heroku dev
HEROKU_OVERRIDES: dict[str, str] = {
    "APP_ENV": "production",
    "DEBUG": "false",
    "FRONTEND_URL": "https://dev-epoint-crm-frontend-4985af85e0a2.herokuapp.com",
    "CORS_ORIGINS": "https://dev-epoint-crm-frontend-4985af85e0a2.herokuapp.com",
    "BACKEND_PUBLIC_URL": "https://dev-epoint-crm-backend-3807e7e86dca.herokuapp.com",
    "S3_STORAGE_PREFIX": "dev/",
    "DOCUSIGN_DEFAULT_TEMPLATE_ROLE_NAME": "Cliente",
}


def parse_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(path)
    content = path.read_text(encoding="utf-8")
    # No usar \s* tras "=": comería saltos de línea y asignaría la clave siguiente
    # (p. ej. PAYPAL_WEBHOOK_ID vacío + DOCUSIGN_PRIVATE_KEY multilínea).
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

    # Valores entre comillas multilínea (p. ej. DOCUSIGN_PRIVATE_KEY)
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


def main() -> int:
    env = parse_env(BACKEND_ENV)
    env.update(HEROKU_OVERRIDES)

    if "DOCUSIGN_PRIVATE_KEY" in env:
        env["DOCUSIGN_PRIVATE_KEY"] = pem_to_heroku(env["DOCUSIGN_PRIVATE_KEY"])

    skip = {"REDIS_URL"}  # Heroku Redis si se agrega addon; local no aplica
    # Claves vacías en .env no se suben; además se limpian en Heroku si quedaron
    # contaminadas (p.ej. EMAIL_DEV_REDIRECT_TO= + línea siguiente pegada).
    empty_keys = sorted(k for k, v in env.items() if k not in skip and not v.strip())
    if empty_keys:
        print(f"Quitando {len(empty_keys)} vars vacías de {HEROKU_APP}: {', '.join(empty_keys)}")
        unset = [HEROKU_BIN, "config:unset", *empty_keys, "-a", HEROKU_APP]
        result = subprocess.run(unset, check=False)
        if result.returncode != 0:
            return result.returncode

    items = [(k, v) for k, v in env.items() if k not in skip and v.strip()]
    batch_size = 8
    print(f"Subiendo {len(items)} variables a {HEROKU_APP}...")
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        pairs = [f"{k}={v}" for k, v in batch]
        cmd = [HEROKU_BIN, "config:set", *pairs, "-a", HEROKU_APP]
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
