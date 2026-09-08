from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.security import generate_password_reset_token, hash_password, hash_password_reset_token, verify_password
from app.models.client import Client
from app.models.password_reset_token import PasswordResetToken
from app.models.role import Role
from app.models.session import UserSession
from app.models.user import User
from app.schemas.auth import ForgotPasswordRequest, ResetPasswordRequest
from app.services.auth import AuthService, PASSWORD_RESET_SENT_MESSAGE


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    tables = [
        Role.__table__,
        User.__table__,
        UserSession.__table__,
        PasswordResetToken.__table__,
        Client.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    admin_role = Role(id=1, code="ADMIN", name="Admin", description="")
    client_role = Role(id=2, code="CLIENT", name="Client", description="")
    admin_user = User(
        id=1,
        email="admin@test.com",
        password_hash=hash_password("Oldpass12"),
        first_name="Admin",
        last_name="User",
        role_id=1,
        is_active=True,
    )
    client_user = User(
        id=2,
        email="client@test.com",
        password_hash=hash_password("Oldpass12"),
        first_name="Client",
        last_name="User",
        role_id=2,
        client_id=1,
        is_active=True,
    )
    inactive_user = User(
        id=3,
        email="inactive@test.com",
        password_hash=hash_password("Oldpass12"),
        first_name="Inactive",
        last_name="User",
        role_id=2,
        is_active=False,
    )
    session.add_all([admin_role, client_role, admin_user, client_user, inactive_user])
    session.commit()
    yield session
    session.close()


def test_request_password_reset_hides_whether_email_exists(db_session):
    service = AuthService(db_session)

    with patch("app.services.auth.send_password_reset_email", return_value=True) as mock_send:
        admin_result = service.request_password_reset(ForgotPasswordRequest(email="admin@test.com"))
        client_result = service.request_password_reset(ForgotPasswordRequest(email="client@test.com"))
        inactive = service.request_password_reset(ForgotPasswordRequest(email="inactive@test.com"))
        unknown = service.request_password_reset(ForgotPasswordRequest(email="unknown@test.com"))

    assert admin_result.message == PASSWORD_RESET_SENT_MESSAGE
    assert client_result.message == PASSWORD_RESET_SENT_MESSAGE
    assert inactive.message == PASSWORD_RESET_SENT_MESSAGE
    assert unknown.message == PASSWORD_RESET_SENT_MESSAGE
    assert mock_send.call_count == 2
    sent_emails = {call.args[0].recipient_email for call in mock_send.call_args_list}
    assert sent_emails == {"admin@test.com", "client@test.com"}
    for call in mock_send.call_args_list:
        payload = call.args[0]
        assert "/recuperar-contrasena/confirmar?token=" in payload.reset_url
        assert len(payload.reset_url.split("token=", 1)[1]) >= 20


def test_reset_password_updates_hash_and_marks_token_used(db_session):
    service = AuthService(db_session)
    raw_token = generate_password_reset_token()
    db_session.add(
        PasswordResetToken(
            user_id=2,
            token_hash=hash_password_reset_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    db_session.commit()

    result = service.reset_password(
        ResetPasswordRequest(token=raw_token, new_password="Newpass12")
    )

    assert result.message == "Contraseña actualizada correctamente"
    user = db_session.get(User, 2)
    assert user is not None
    assert verify_password("Newpass12", user.password_hash)
    token_row = db_session.execute(select(PasswordResetToken)).scalar_one()
    assert token_row.used_at is not None


def test_reset_password_updates_staff_user(db_session):
    service = AuthService(db_session)
    raw_token = generate_password_reset_token()
    db_session.add(
        PasswordResetToken(
            user_id=1,
            token_hash=hash_password_reset_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    db_session.commit()

    result = service.reset_password(
        ResetPasswordRequest(token=raw_token, new_password="Newpass12")
    )

    assert result.message == "Contraseña actualizada correctamente"
    user = db_session.get(User, 1)
    assert user is not None
    assert verify_password("Newpass12", user.password_hash)


def test_reset_password_rejects_invalid_token(db_session):
    service = AuthService(db_session)
    with pytest.raises(HTTPException) as exc:
        service.reset_password(
            ResetPasswordRequest(token="invalid-token-value-xyz", new_password="Newpass12")
        )
    assert exc.value.status_code == 400
