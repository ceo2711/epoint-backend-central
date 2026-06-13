"""
Crea la plantilla de bienvenida ePoint en Twilio Content API y envía un mensaje de prueba.

Uso:
  cd backend && python scripts/twilio_whatsapp_setup.py
  python scripts/twilio_whatsapp_setup.py --send-only --content-sid HX...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

TEMPLATE_BODY = """Hola {{1}}, bienvenido/a a ePoint.

Tu cuenta fue aprobada. Ingresa al portal para completar tus datos y documentos:

Portal: {{2}}
Usuario: {{3}}
Contrasena temporal: {{4}}

En tu primer ingreso deberas cambiar la contrasena."""

FRIENDLY_NAME = "epoint_client_approved_es"


def auth() -> tuple[str, str]:
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        print("Faltan TWILIO_ACCOUNT_SID o TWILIO_AUTH_TOKEN en .env", file=sys.stderr)
        sys.exit(1)
    return sid, token


def create_content_template(sid: str, token: str) -> str:
    payload = {
        "friendly_name": FRIENDLY_NAME,
        "language": "es",
        "variables": {
            "1": "nombre_cliente",
            "2": "url_portal",
            "3": "email",
            "4": "contrasena_temporal",
        },
        "types": {
            "twilio/text": {
                "body": TEMPLATE_BODY,
            }
        },
    }
    response = httpx.post(
        "https://content.twilio.com/v1/Content",
        auth=(sid, token),
        json=payload,
        timeout=60,
    )
    if response.status_code >= 400:
        print("Error creando plantilla:", response.status_code, response.text, file=sys.stderr)
        sys.exit(1)
    data = response.json()
    content_sid = data["sid"]
    print(f"Plantilla creada: {content_sid} ({data.get('friendly_name')})")
    return content_sid


def find_existing_template(sid: str, token: str) -> str | None:
    response = httpx.get(
        "https://content.twilio.com/v1/Content",
        auth=(sid, token),
        params={"PageSize": 50},
        timeout=60,
    )
    response.raise_for_status()
    for item in response.json().get("contents", []):
        if item.get("friendly_name") == FRIENDLY_NAME:
            return item["sid"]
    return None


def request_whatsapp_approval(sid: str, token: str, content_sid: str) -> None:
    from_number = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886").replace("whatsapp:", "")
    payload = {
        "name": FRIENDLY_NAME,
        "category": "UTILITY",
        "content_sid": content_sid,
    }
    response = httpx.post(
        f"https://content.twilio.com/v1/Content/{content_sid}/ApprovalRequests/whatsapp",
        auth=(sid, token),
        json=payload,
        timeout=60,
    )
    if response.status_code >= 400:
        print("Aviso: no se pudo solicitar aprobacion WhatsApp automaticamente:")
        print(response.status_code, response.text)
        print("En Sandbox puede funcionar igual; revisa Twilio Console → Content Editor.")
        return
    print("Solicitud de aprobacion WhatsApp enviada:", response.json())


def send_test_message(sid: str, token: str, content_sid: str, to_phone: str) -> None:
    from twilio.rest import Client

    from app.core.phone import normalize_whatsapp_number

    to_e164 = normalize_whatsapp_number(to_phone, "54")
    from_whatsapp = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    if not from_whatsapp.startswith("whatsapp:"):
        from_whatsapp = f"whatsapp:{from_whatsapp}"

    variables = {
        "1": "Cliente de prueba",
        "2": os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/") + "/login",
        "3": "cliente@epoint.com",
        "4": "Test123!",
    }

    print(f"Enviando prueba a whatsapp:{to_e164} con plantilla {content_sid}")
    client = Client(sid, token)
    message = client.messages.create(
        from_=from_whatsapp,
        to=f"whatsapp:{to_e164}",
        content_sid=content_sid,
        content_variables=json.dumps(variables),
    )
    print(f"Mensaje enviado: sid={message.sid} status={message.status}")


def update_env_content_sid(content_sid: str) -> None:
    env_path = ROOT / ".env"
    text = env_path.read_text(encoding="utf-8")
    key = "TWILIO_WHATSAPP_CLIENT_APPROVED_CONTENT_SID="
    if key not in text:
        print("No se encontro la clave en .env; agregala manualmente:", content_sid)
        return
    lines = []
    for line in text.splitlines():
        if line.startswith(key):
            lines.append(f"{key}{content_sid}")
        else:
            lines.append(line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f".env actualizado con {content_sid}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-only", action="store_true")
    parser.add_argument("--content-sid", default="")
    parser.add_argument("--phone", default="1164509627")
    parser.add_argument("--skip-env-update", action="store_true")
    args = parser.parse_args()

    sid, token = auth()

    if args.send_only:
        content_sid = args.content_sid or os.environ.get("TWILIO_WHATSAPP_CLIENT_APPROVED_CONTENT_SID", "")
        if not content_sid or content_sid.startswith("HXtu_"):
            print("Indica un content SID valido con --content-sid o en .env", file=sys.stderr)
            sys.exit(1)
    else:
        content_sid = find_existing_template(sid, token)
        if content_sid:
            print(f"Reutilizando plantilla existente: {content_sid}")
        else:
            content_sid = create_content_template(sid, token)
            request_whatsapp_approval(sid, token, content_sid)
        if not args.skip_env_update:
            update_env_content_sid(content_sid)

    send_test_message(sid, token, content_sid, args.phone)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
