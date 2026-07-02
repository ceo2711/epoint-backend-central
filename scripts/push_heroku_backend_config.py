#!/usr/bin/env python3
"""Sube variables de backend/.env a Heroku (sin commitear secretos)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
HEROKU_APP = "dev-epoint-crm-backend"

# Overrides para producción en Heroku dev
HEROKU_OVERRIDES: dict[str, str] = {
    "APP_ENV": "production",
    "DEBUG": "false",
    "FRONTEND_URL": "https://dev-epoint-crm-frontend-4985af85e0a2.herokuapp.com",
    "CORS_ORIGINS": "https://dev-epoint-crm-frontend-4985af85e0a2.herokuapp.com",
    "BACKEND_PUBLIC_URL": "https://dev-epoint-crm-backend-3807e7e86dca.herokuapp.com",
    "S3_STORAGE_PREFIX": "dev/",
}


def parse_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(path)
    content = path.read_text(encoding="utf-8")
    for match in re.finditer(
        r'^([A-Z][A-Z0-9_]*)\s*=\s*("(?:[^"\\]|\\.)*"|[^\n#]+)',
        content,
        re.MULTILINE,
    ):
        key, raw = match.group(1), match.group(2).strip()
        if raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]
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
    items = [(k, v) for k, v in env.items() if k not in skip and v.strip()]
    batch_size = 8
    print(f"Subiendo {len(items)} variables a {HEROKU_APP}...")
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        pairs = [f"{k}={v}" for k, v in batch]
        cmd = ["heroku", "config:set", *pairs, "-a", HEROKU_APP]
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
