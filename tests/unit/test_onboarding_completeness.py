from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.address import Address
from app.models.client import Client
from app.models.document import Document
from app.models.enums import ClientStatus, DocumentVerificationStatus
from app.models.role import Role
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.onboarding_completeness import (
    REMINDER_ELIGIBLE_STATUSES,
    REMINDER_EXCLUDED_STATUSES,
    analyze_onboarding_gaps,
    client_needs_onboarding_reminder,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    tables = [
        Client.__table__,
        Address.__table__,
        Vehicle.__table__,
        Document.__table__,
        Role.__table__,
        User.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_client(**kwargs) -> Client:
    defaults = {
        "id": 1,
        "status": ClientStatus.EN_CARGA_DATOS.value,
        "first_name": "Ana",
        "last_name": "García",
        "email": "ana@example.com",
        "phone": "+15551234567",
        "registered_by_user_id": 1,
        "approved_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    return Client(**defaults)


def _add_active_portal_user(db_session, client: Client) -> User:
    role = Role(id=1, code="CLIENT", name="Cliente")
    db_session.add(role)
    db_session.flush()
    user = User(
        email=client.email,
        password_hash="hash",
        first_name=client.first_name,
        last_name=client.last_name,
        role_id=role.id,
        client_id=client.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_analyze_gaps_all_profile_and_documents_missing(db_session):
    client = _make_client()
    db_session.add(client)
    db_session.commit()

    gaps = analyze_onboarding_gaps(db_session, client)

    assert "SSN / Seguro Social" in gaps.profile_items
    assert "Fecha de nacimiento" in gaps.profile_items
    assert "Dirección actual" in gaps.profile_items
    assert "Datos del vehículo" in gaps.profile_items
    assert any("Tarjeta SSN" in item for item in gaps.missing_documents)
    assert gaps.needs_reminder is True


def _seed_complete_profile(db_session, client: Client) -> None:
    db_session.add(
        Address(
            client_id=client.id,
            type="CURRENT",
            street="123 Main",
            city="Orlando",
            state="FL",
            zip_code="32801",
        )
    )
    db_session.add(
        Vehicle(client_id=client.id, order=1, model="Toyota", year=2020, color="Blue")
    )


def _add_document(db_session, client: Client, doc_type: str, status: str) -> None:
    db_session.add(
        Document(
            client_id=client.id,
            type=doc_type,
            storage_key=f"key/{doc_type}",
            original_filename=f"{doc_type}.pdf",
            mime_type="application/pdf",
            verification_status=status,
        )
    )


def test_analyze_gaps_complete_client(db_session):
    client = _make_client(
        ssn_encrypted="enc",
        date_of_birth=date(1990, 5, 10),
    )
    db_session.add(client)
    db_session.flush()
    _seed_complete_profile(db_session, client)
    for doc_type in (
        "SSN_CARD",
        "DRIVERS_LICENSE_FRONT",
        "DRIVERS_LICENSE_BACK",
        "UTILITY_BILL",
    ):
        _add_document(db_session, client, doc_type, DocumentVerificationStatus.APROBADO.value)
    db_session.commit()

    gaps = analyze_onboarding_gaps(db_session, client)

    assert gaps.needs_reminder is False


def test_analyze_gaps_ignores_rejected_license_when_passport_uploaded(db_session):
    client = _make_client(
        ssn_encrypted="enc",
        date_of_birth=date(1990, 5, 10),
    )
    db_session.add(client)
    db_session.flush()
    _seed_complete_profile(db_session, client)
    _add_document(db_session, client, "SSN_CARD", DocumentVerificationStatus.APROBADO.value)
    _add_document(db_session, client, "DRIVERS_LICENSE_FRONT", DocumentVerificationStatus.RECHAZADO.value)
    _add_document(db_session, client, "DRIVERS_LICENSE_BACK", DocumentVerificationStatus.RECHAZADO.value)
    _add_document(db_session, client, "PASSPORT", DocumentVerificationStatus.PENDIENTE.value)
    _add_document(db_session, client, "UTILITY_BILL", DocumentVerificationStatus.APROBADO.value)
    db_session.commit()

    gaps = analyze_onboarding_gaps(db_session, client)

    assert gaps.needs_reminder is False
    assert gaps.rejected_documents == []
    assert not any("Licencia" in item for item in gaps.all_pending_labels())


def test_analyze_gaps_passport_path_complete_with_bank_statement(db_session):
    client = _make_client(
        ssn_encrypted="enc",
        date_of_birth=date(1990, 5, 10),
    )
    db_session.add(client)
    db_session.flush()
    _seed_complete_profile(db_session, client)
    _add_document(db_session, client, "SSN_CARD", DocumentVerificationStatus.APROBADO.value)
    _add_document(db_session, client, "PASSPORT", DocumentVerificationStatus.APROBADO.value)
    _add_document(db_session, client, "BANK_STATEMENT", DocumentVerificationStatus.APROBADO.value)
    _add_document(db_session, client, "UTILITY_BILL", DocumentVerificationStatus.PENDIENTE.value)
    db_session.commit()

    gaps = analyze_onboarding_gaps(db_session, client)

    assert gaps.needs_reminder is False


def test_analyze_gaps_pending_address_does_not_trigger_reminder(db_session):
    client = _make_client(
        ssn_encrypted="enc",
        date_of_birth=date(1990, 5, 10),
    )
    db_session.add(client)
    db_session.flush()
    _seed_complete_profile(db_session, client)
    _add_document(db_session, client, "SSN_CARD", DocumentVerificationStatus.APROBADO.value)
    _add_document(db_session, client, "PASSPORT", DocumentVerificationStatus.APROBADO.value)
    _add_document(db_session, client, "UTILITY_BILL", DocumentVerificationStatus.PENDIENTE.value)
    db_session.commit()

    gaps = analyze_onboarding_gaps(db_session, client)

    assert gaps.needs_reminder is False


def test_analyze_gaps_english_labels(db_session):
    client = _make_client()
    db_session.add(client)
    db_session.commit()

    gaps = analyze_onboarding_gaps(db_session, client, locale="en")

    assert "SSN / Social Security Number" in gaps.profile_items
    assert any("SSN card" in item for item in gaps.missing_documents)


def test_analyze_gaps_rejected_document(db_session):
    client = _make_client(
        ssn_encrypted="enc",
        date_of_birth=date(1990, 5, 10),
    )
    db_session.add(client)
    db_session.flush()
    db_session.add(
        Address(
            client_id=client.id,
            type="CURRENT",
            street="123 Main",
            city="Orlando",
            state="FL",
            zip_code="32801",
        )
    )
    db_session.add(
        Vehicle(client_id=client.id, order=1, model="Toyota", year=2020, color="Blue")
    )
    db_session.add(
        Document(
            client_id=client.id,
            type="SSN_CARD",
            storage_key="key/ssn",
            original_filename="ssn.pdf",
            mime_type="application/pdf",
            verification_status=DocumentVerificationStatus.RECHAZADO.value,
        )
    )
    db_session.commit()

    gaps = analyze_onboarding_gaps(db_session, client)

    assert any("Tarjeta SSN" in item and "rechazado" in item for item in gaps.rejected_documents)
    assert gaps.needs_reminder is True


def test_client_needs_reminder_skips_wrong_status(db_session):
    client = _make_client(status=ClientStatus.LISTO_PARA_TABLERO.value)
    db_session.add(client)
    db_session.commit()
    _add_active_portal_user(db_session, client)

    assert client_needs_onboarding_reminder(db_session, client) is False


def test_client_needs_reminder_requires_active_portal_user(db_session):
    client = _make_client()
    db_session.add(client)
    db_session.commit()

    assert client_needs_onboarding_reminder(db_session, client) is False


def test_client_needs_reminder_skips_inactive_portal_user(db_session):
    client = _make_client()
    db_session.add(client)
    db_session.flush()
    role = Role(id=1, code="CLIENT", name="Cliente")
    db_session.add(role)
    db_session.flush()
    db_session.add(
        User(
            email=client.email,
            password_hash="hash",
            first_name=client.first_name,
            last_name=client.last_name,
            role_id=role.id,
            client_id=client.id,
            is_active=False,
        )
    )
    db_session.commit()

    assert client_needs_onboarding_reminder(db_session, client) is False


def test_client_needs_reminder_when_active_portal_user_and_gaps(db_session):
    client = _make_client()
    db_session.add(client)
    db_session.commit()
    _add_active_portal_user(db_session, client)

    assert client_needs_onboarding_reminder(db_session, client) is True


def test_reminder_eligible_statuses_cover_onboarding_flow():
    assert ClientStatus.EN_CARGA_DATOS.value in REMINDER_ELIGIBLE_STATUSES
    assert ClientStatus.APROBADO_PARA_ONBOARDING.value in REMINDER_ELIGIBLE_STATUSES


def test_reminder_excluded_statuses_block_inactive_clients():
    assert ClientStatus.INACTIVO.value in REMINDER_EXCLUDED_STATUSES
    assert ClientStatus.RECHAZADO.value in REMINDER_EXCLUDED_STATUSES


def test_onboarding_reminder_templates_support_english():
    from app.services.notifications.templates import (
        onboarding_reminder_email_body,
        onboarding_reminder_whatsapp_body,
    )

    email = onboarding_reminder_email_body(
        first_name="John",
        pending_items=["SSN card"],
        portal_login_url="https://portal.example.com",
        locale="en",
    )
    whatsapp = onboarding_reminder_whatsapp_body(
        first_name="John",
        pending_items=["SSN card"],
        portal_login_url="https://portal.example.com",
        locale="en",
    )

    assert "Hi John" in email
    assert "SSN card" in email
    assert "Hi John" in whatsapp
