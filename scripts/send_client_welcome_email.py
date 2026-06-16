"""Reenvía o prueba el correo de bienvenida para un cliente por email.

Uso:
  python scripts/send_client_welcome_email.py --email cliente@ejemplo.com
  python scripts/send_client_welcome_email.py --email cliente@ejemplo.com \\
      --first-name Juan --temp-password Temp123! --portal-url https://app.ePoint.com/login
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.client import Client
from app.models.user import User
from app.services.email import ClientWelcomeEmailPayload, send_client_welcome_email


def _build_payload_from_args(args: argparse.Namespace) -> ClientWelcomeEmailPayload:
    email = args.email.lower().strip()
    settings = get_settings()

    if args.first_name and args.temp_password:
        return ClientWelcomeEmailPayload(
            recipient_email=email,
            first_name=args.first_name,
            temp_password=args.temp_password,
            portal_login_url=args.portal_url or settings.portal_login_url,
            client_id=args.client_id,
        )

    with SessionLocal() as db:
        client = db.execute(select(Client).where(Client.email == email)).scalar_one_or_none()
        if client is None:
            raise SystemExit(f"No se encontró cliente con email {email}")

        portal_user = db.execute(
            select(User).where(User.client_id == client.id, User.is_active.is_(True))
        ).scalar_one_or_none()
        if portal_user is None:
            raise SystemExit(f"El cliente {email} no tiene usuario de portal activo")

        if not args.temp_password:
            raise SystemExit(
                "El cliente existe pero no se pasó --temp-password. "
                "Generá una contraseña temporal desde el CRM o pasala por argumento."
            )

        return ClientWelcomeEmailPayload(
            recipient_email=email,
            first_name=client.first_name,
            temp_password=args.temp_password,
            portal_login_url=args.portal_url or settings.portal_login_url,
            client_id=client.id,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Envía el correo de bienvenida a un cliente")
    parser.add_argument("--email", required=True, help="Email del cliente (destinatario)")
    parser.add_argument("--first-name", help="Nombre del cliente (opcional si existe en BD)")
    parser.add_argument("--temp-password", help="Contraseña temporal del portal")
    parser.add_argument("--portal-url", help="URL de login del portal")
    parser.add_argument("--client-id", type=int, help="ID del cliente (solo informativo en logs)")
    args = parser.parse_args()

    payload = _build_payload_from_args(args)
    ok = send_client_welcome_email(payload)
    if ok:
        print(f"OK: solicitud de bienvenida procesada para {payload.recipient_email}")
    else:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
