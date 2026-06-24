from email_validator import EmailNotValidError, validate_email

from app.models.client import Client
from app.services.clients import ClientService


def validate_approval_requirements(client: Client, client_service: ClientService) -> list[str]:
    """Campos mínimos para aprobar un cliente (pre-onboarding)."""
    issues: list[str] = []

    if not client.first_name or not client.first_name.strip():
        issues.append("Nombre vacío")
    if not client.last_name or not client.last_name.strip():
        issues.append("Apellido vacío")
    if not client.email or not client.email.strip():
        issues.append("Email vacío")
    else:
        try:
            validate_email(client.email.strip(), check_deliverability=False)
        except EmailNotValidError:
            issues.append("Email con formato inválido")

    if not client.phone or len(client.phone.strip()) < 5:
        issues.append("Teléfono inválido o muy corto")

    if not client.source or not str(client.source).strip():
        issues.append("Fuente sin definir")

    if not client.merchant_id:
        issues.append("Comercio sin definir")

    duplicate_email = client_service.find_client_with_email(client.email, exclude_client_id=client.id)
    if duplicate_email:
        issues.append(f"Email duplicado (cliente #{duplicate_email.id})")

    duplicate_phone = client_service.find_client_with_phone(client.phone, exclude_client_id=client.id)
    if duplicate_phone:
        issues.append(f"Teléfono duplicado (cliente #{duplicate_phone.id})")

    return issues
