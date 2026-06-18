"""Reenvía o prueba el WhatsApp de bienvenida para un cliente por teléfono.

Uso:
  python scripts/send_client_welcome_whatsapp.py --phone 1131432490
  python scripts/send_client_welcome_whatsapp.py --phone +5491131432490 \\
      --first-name Juan --email cliente@ejemplo.com --temp-password Temp123!
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.clients import ClientService
from app.services.whatsapp import ClientWelcomeWhatsAppPayload, send_client_welcome_whatsapp


def _build_payload_from_args(args: argparse.Namespace) -> ClientWelcomeWhatsAppPayload:
    phone = args.phone.strip()
    settings = get_settings()

    if args.first_name and args.email and args.temp_password:
        return ClientWelcomeWhatsAppPayload(
            recipient_phone=phone,
            first_name=args.first_name,
            email=args.email.lower().strip(),
            temp_password=args.temp_password,
            portal_login_url=args.portal_url or settings.portal_login_url,
            client_id=args.client_id,
        )

    with SessionLocal() as db:
        client_service = ClientService(db)
        client = client_service.find_client_with_phone(phone)
        if client is None:
            raise SystemExit(f"No se encontró cliente con teléfono {phone}")

        if not args.temp_password:
            raise SystemExit(
                "El cliente existe pero no se pasó --temp-password. "
                "Generá una contraseña temporal desde el CRM o pasala por argumento."
            )

        return ClientWelcomeWhatsAppPayload(
            recipient_phone=client.phone,
            first_name=client.first_name,
            email=client.email,
            temp_password=args.temp_password,
            portal_login_url=args.portal_url or settings.portal_login_url,
            client_id=client.id,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Envía el WhatsApp de bienvenida a un cliente")
    parser.add_argument("--phone", required=True, help="Teléfono del cliente (destinatario)")
    parser.add_argument("--first-name", help="Nombre del cliente (opcional si existe en BD)")
    parser.add_argument("--email", help="Email del cliente para el mensaje")
    parser.add_argument("--temp-password", help="Contraseña temporal del portal")
    parser.add_argument("--portal-url", help="URL de login del portal")
    parser.add_argument("--client-id", type=int, help="ID del cliente (solo informativo en logs)")
    args = parser.parse_args()

    payload = _build_payload_from_args(args)
    ok = send_client_welcome_whatsapp(payload)
    if ok:
        print(f"OK: solicitud de bienvenida WhatsApp procesada para {payload.recipient_phone}")
    else:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
