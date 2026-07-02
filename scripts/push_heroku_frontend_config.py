#!/usr/bin/env python3
"""Sube variables de frontend/.env.local a Heroku."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

FRONTEND_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env.local"
HEROKU_APP = "dev-epoint-crm-frontend"
HEROKU_BIN = shutil.which("heroku") or r"C:\Program Files\heroku\bin\heroku.cmd"

HEROKU_OVERRIDES: dict[str, str] = {
    "NEXT_PUBLIC_API_URL": "https://dev-epoint-crm-backend-3807e7e86dca.herokuapp.com/api/v1",
    "NEXT_PUBLIC_CALENDLY_WRITE_ENABLED": "false",
}


def parse_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(path)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def main() -> int:
    env = parse_env(FRONTEND_ENV)
    env.update(HEROKU_OVERRIDES)
    pairs = [f"{k}={v}" for k, v in env.items() if v.strip()]
    print(f"Subiendo {len(pairs)} variables a {HEROKU_APP}...")
    cmd = [HEROKU_BIN, "config:set", *pairs, "-a", HEROKU_APP]
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
