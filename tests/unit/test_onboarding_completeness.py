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


def test_analyze_gaps_complete_client(db_session):
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
    for doc_type in (
        "SSN_CARD",
        "DRIVERS_LICENSE_FRONT",
        "DRIVERS_LICENSE_BACK",
        "UTILITY_BILL",
    ):
        db_session.add(
            Document(
                client_id=client.id,
                type=doc_type,
                storage_key=f"key/{doc_type}",
                original_filename=f"{doc_type}.pdf",
                mime_type="application/pdf",
                verification_status=DocumentVerificationStatus.APROBADO.value,
            )
        )
    db_session.commit()

    gaps = analyze_onboarding_gaps(db_session, client)

    assert gaps.needs_reminder is False


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
