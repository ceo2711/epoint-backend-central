"""Trae inbounds de Resend y los postea al webhook local (sin JWT)."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    vals: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        vals[key.strip()] = value.strip().strip('"').strip("'")
    return vals


def resend_get(url: str, api_key: str) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def main() -> int:
    env = load_env()
    api_key = env.get("RESEND_API_KEY", "")
    if not api_key:
        print("Falta RESEND_API_KEY")
        return 1

    listed = resend_get("https://api.resend.com/emails/receiving", api_key)
    items = listed.get("data") or []
    if not items:
        print("No hay emails en Receiving")
        return 1

    latest = items[0]
    email_id = latest["id"]
    detail = resend_get(f"https://api.resend.com/emails/receiving/{email_id}", api_key)
    payload = {
        "from": detail.get("from") or latest.get("from"),
        "to": detail.get("to") or latest.get("to") or [],
        "subject": detail.get("subject") or latest.get("subject") or "",
        "text": detail.get("text") or "",
        "html": detail.get("html") or "",
        "email_id": email_id,
    }
    print(f"Sync {payload['from']} → {payload['subject']}")

    base = (env.get("BACKEND_PUBLIC_URL") or "http://localhost:8000").rstrip("/")
    prefix = env.get("API_PREFIX") or "/api/v1"
    url = f"{base}{prefix}/webhooks/resend/inbound"
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode())
    print(json.dumps(result))
    return 0 if result.get("ingested") else 2


if __name__ == "__main__":
    sys.exit(main())
