import secrets
import string
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.encryption import encrypt_value
from app.core.security import hash_password
from app.models.client import Client
from app.models.client_assignment import ClientAssignment
from app.models.enums import ClientStatus, NotificationEventType
from app.models.role import Role
from app.models.user import User
from app.services.audit import AuditService
from app.services.boards.service import BoardService
from app.core.config import get_settings
from app.core.phone import phones_match
from app.services.notifications import NotificationService
from app.services.notifications.templates import (
    client_approved_email_body,
    client_approved_in_app_body,
    client_approved_whatsapp_body,
    client_approved_whatsapp_content_variables,
)


def _generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class ClientService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.notifications = NotificationService(db)
        self.audit = AuditService(db)
        self.boards = BoardService(db)

    def find_client_with_email(self, email: str, exclude_client_id: int | None = None) -> Client | None:
        normalized = email.lower().strip()
        query = select(Client).where(Client.email == normalized)
        if exclude_client_id is not None:
            query = query.where(Client.id != exclude_client_id)
        return self.db.execute(query).scalar_one_or_none()

    def find_client_with_phone(self, phone: str, exclude_client_id: int | None = None) -> Client | None:
        settings = get_settings()
        country_code = settings.whatsapp_default_country_code
        query = select(Client)
        if exclude_client_id is not None:
            query = query.where(Client.id != exclude_client_id)
        for client in self.db.execute(query).scalars().all():
            if phones_match(client.phone, phone, country_code):
                return client
        return None

    def _conflict_payload(self, client: Client) -> dict:
        return {
            "client_id": client.id,
            "client_name": client.full_name,
            "client_email": client.email,
        }

    def assert_email_available(self, email: str, *, exclude_client_id: int | None = None) -> None:
        duplicate = self.find_client_with_email(email, exclude_client_id)
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El email ya está registrado por {duplicate.full_name} (cliente #{duplicate.id})",
            )

    def assert_phone_available(self, phone: str, *, exclude_client_id: int | None = None) -> None:
        duplicate = self.find_client_with_phone(phone, exclude_client_id)
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El teléfono ya está registrado por {duplicate.full_name} (cliente #{duplicate.id})",
            )

    def check_contact_availability(
        self,
        *,
        email: str | None = None,
        phone: str | None = None,
        exclude_client_id: int | None = None,
    ) -> dict:
        result: dict = {"available": True, "email": None, "phone": None}
        if email and "@" in email:
            duplicate = self.find_client_with_email(email, exclude_client_id)
            if duplicate:
                result["available"] = False
                result["email"] = self._conflict_payload(duplicate)
        if phone and len(phone.strip()) >= 5:
            duplicate = self.find_client_with_phone(phone, exclude_client_id)
            if duplicate:
                result["available"] = False
                result["phone"] = self._conflict_payload(duplicate)
        return result

    def create_client(
        self,
        *,
        actor: User,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
    ) -> Client:
        normalized_email = email.lower().strip()
        normalized_phone = phone.strip()
        self.assert_email_available(normalized_email)
        self.assert_phone_available(normalized_phone)
        client = Client(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            email=normalized_email,
            phone=normalized_phone,
            registered_by_user_id=actor.id,
            status=ClientStatus.PENDIENTE_DE_REVISION.value,
        )
        self.db.add(client)
        self.db.flush()

        onboarding_users = self._get_onboarding_team()
        self.notifications.notify(
            event_type=NotificationEventType.NEW_CLIENT_PENDING_REVIEW.value,
            users=onboarding_users,
            title="Nuevo cliente para revisar",
            body=f"{client.full_name} fue registrado y espera revisión.",
            payload={"client_id": client.id},
        )
        self.audit.log(
            actor=actor,
            action="CLIENT_CREATED",
            entity_type="client",
            entity_id=client.id,
        )
        self.db.commit()
        self.db.refresh(client)
        return client

    def update_client(
        self,
        *,
        actor: User,
        client: Client,
        **fields,
    ) -> Client:
        if "email" in fields and fields["email"] is not None:
            self.assert_email_available(fields["email"], exclude_client_id=client.id)
        if "phone" in fields and fields["phone"] is not None:
            self.assert_phone_available(fields["phone"], exclude_client_id=client.id)
        for key, value in fields.items():
            if value is not None and hasattr(client, key):
                if key == "email" and value:
                    setattr(client, key, value.lower().strip())
                elif isinstance(value, str):
                    setattr(client, key, value.strip())
                else:
                    setattr(client, key, value)
        self.audit.log(actor=actor, action="CLIENT_UPDATED", entity_type="client", entity_id=client.id)
        self.db.commit()
        self.db.refresh(client)
        return client

    def resubmit_for_review(self, *, actor: User, client: Client) -> Client:
        if client.status != ClientStatus.RECHAZADO.value:
            raise HTTPException(status_code=400, detail="Solo clientes rechazados pueden reenviarse a revisión")
        client.status = ClientStatus.PENDIENTE_DE_REVISION.value
        client.rejection_reason = None
        client.rejected_at = None
        self.notifications.mark_client_events_read(
            client_id=client.id,
            event_types=[NotificationEventType.CLIENT_REJECTED.value],
            user_ids=[actor.id],
        )
        onboarding_users = self._get_onboarding_team()
        self.notifications.notify(
            event_type=NotificationEventType.NEW_CLIENT_PENDING_REVIEW.value,
            users=onboarding_users,
            title="Cliente reenviado a revisión",
            body=f"{client.full_name} fue corregido y reenviado.",
            payload={"client_id": client.id},
        )
        self.db.commit()
        self.db.refresh(client)
        return client

    def reject_client(self, *, actor: User, client: Client, reason: str) -> Client:
        if client.status not in (
            ClientStatus.PENDIENTE_DE_REVISION.value,
            ClientStatus.APROBADO_PARA_ONBOARDING.value,
        ):
            raise HTTPException(status_code=400, detail="El cliente no puede ser rechazado en su estado actual")
        client.status = ClientStatus.RECHAZADO.value
        client.rejection_reason = reason.strip()
        client.rejected_at = datetime.now(timezone.utc)

        self.notifications.mark_client_events_read(
            client_id=client.id,
            event_types=[NotificationEventType.NEW_CLIENT_PENDING_REVIEW.value],
        )
        vendor = self.db.get(User, client.registered_by_user_id)
        if vendor:
            self.notifications.notify(
                event_type=NotificationEventType.CLIENT_REJECTED.value,
                users=[vendor],
                title="Cliente rechazado",
                body=f"{client.full_name} fue rechazado. Motivo: {reason}",
                payload={"client_id": client.id, "reason": reason},
            )
        self.audit.log(
            actor=actor,
            action="CLIENT_REJECTED",
            entity_type="client",
            entity_id=client.id,
            metadata={"reason": reason},
        )
        self.db.commit()
        self.db.refresh(client)
        return client

    def _resolve_portal_user(self, client: Client, client_role: Role, temp_password: str) -> User:
        """Obtiene o crea el usuario portal vinculado a este cliente (no reutiliza otros clientes)."""
        portal_user = (
            self.db.execute(
                select(User)
                .options(joinedload(User.role))
                .join(Role, User.role_id == Role.id)
                .where(User.client_id == client.id, Role.code == "CLIENT")
            )
            .unique()
            .scalar_one_or_none()
        )

        if portal_user is None:
            email_user = (
                self.db.execute(
                    select(User).options(joinedload(User.role)).where(User.email == client.email)
                )
                .unique()
                .scalar_one_or_none()
            )
            if email_user:
                if email_user.role.code != "CLIENT":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="El email del cliente ya está en uso por un usuario interno",
                    )
                if email_user.client_id and email_user.client_id != client.id:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="El email del cliente ya está asociado a otro portal de cliente",
                    )
                portal_user = email_user
            else:
                portal_user = User(
                    email=client.email,
                    password_hash=hash_password(temp_password),
                    first_name=client.first_name,
                    last_name=client.last_name,
                    phone=client.phone,
                    role_id=client_role.id,
                    client_id=client.id,
                    must_change_password=True,
                    is_active=True,
                )
                self.db.add(portal_user)
                self.db.flush()
                return portal_user

        portal_user.password_hash = hash_password(temp_password)
        portal_user.must_change_password = True
        portal_user.client_id = client.id
        portal_user.is_active = True
        portal_user.first_name = client.first_name
        portal_user.last_name = client.last_name
        portal_user.phone = client.phone
        portal_user.role_id = client_role.id
        if portal_user.email != client.email:
            conflict = self.db.execute(
                select(User).where(User.email == client.email, User.id != portal_user.id)
            ).scalar_one_or_none()
            if conflict:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="El email del cliente ya está en uso por otro usuario",
                )
            portal_user.email = client.email
        self.db.flush()
        return portal_user

    def approve_client(
        self,
        *,
        actor: User,
        client: Client,
        advisor_user_id: int,
    ) -> tuple[Client, str]:
        if client.status != ClientStatus.PENDIENTE_DE_REVISION.value:
            raise HTTPException(status_code=400, detail="Solo clientes pendientes pueden aprobarse")

        advisor = self.db.get(User, advisor_user_id)
        if advisor is None or advisor.role.code != "ADVISOR":
            raise HTTPException(status_code=400, detail="Asesor inválido")

        # Desactivar asignación previa
        for assignment in client.assignments:
            if assignment.unassigned_at is None:
                assignment.unassigned_at = datetime.now(timezone.utc)

        self.db.add(
            ClientAssignment(
                client_id=client.id,
                advisor_user_id=advisor_user_id,
                assigned_by_user_id=actor.id,
            )
        )

        client.status = ClientStatus.APROBADO_PARA_ONBOARDING.value
        client.approved_at = datetime.now(timezone.utc)
        client.approved_by_user_id = actor.id

        temp_password = _generate_temp_password()
        client_role = self.db.execute(select(Role).where(Role.code == "CLIENT")).scalar_one()
        portal_user = self._resolve_portal_user(client, client_role, temp_password)

        client.status = ClientStatus.EN_CARGA_DATOS.value

        self.notifications.mark_client_events_read(
            client_id=client.id,
            event_types=[NotificationEventType.NEW_CLIENT_PENDING_REVIEW.value],
        )

        settings = get_settings()
        portal_login_url = settings.portal_login_url
        welcome_title = "¡Bienvenido a ePoint!"
        credential_kwargs = {
            "first_name": client.first_name,
            "email": client.email,
            "temp_password": temp_password,
            "portal_login_url": portal_login_url,
        }
        self.notifications.notify(
            event_type=NotificationEventType.CLIENT_APPROVED.value,
            users=[portal_user],
            title=welcome_title,
            body=client_approved_in_app_body(first_name=client.first_name),
            payload={
                "client_id": client.id,
                "email": client.email,
                "client_phone": client.phone,
                "portal_url": portal_login_url,
                "content_sid": settings.twilio_whatsapp_client_approved_content_sid,
                "content_variables": client_approved_whatsapp_content_variables(**credential_kwargs),
            },
            channel_bodies={
                "IN_APP": client_approved_in_app_body(first_name=client.first_name),
                "EMAIL": client_approved_email_body(**credential_kwargs),
                "WHATSAPP": client_approved_whatsapp_body(**credential_kwargs),
            },
        )

        self.audit.log(
            actor=actor,
            action="CLIENT_APPROVED",
            entity_type="client",
            entity_id=client.id,
            metadata={"advisor_id": advisor_user_id},
        )
        self.ensure_board(client)
        self.db.commit()
        self.db.refresh(client)
        return client, temp_password

    def get_portal_access_info(self, client: Client) -> dict:
        settings = get_settings()
        portal_user = self.db.execute(
            select(User).where(User.client_id == client.id, User.is_active.is_(True))
        ).scalar_one_or_none()
        if portal_user is None:
            return {
                "has_portal_access": False,
                "portal_email": None,
                "portal_login_url": None,
            }
        return {
            "has_portal_access": True,
            "portal_email": portal_user.email,
            "portal_login_url": settings.portal_login_url,
        }

    def reset_portal_password(self, *, actor: User, client: Client) -> tuple[str, str, str]:
        portal_user = self.db.execute(
            select(User).where(User.client_id == client.id, User.is_active.is_(True))
        ).scalar_one_or_none()
        if portal_user is None:
            raise HTTPException(
                status_code=400,
                detail="El cliente aún no tiene acceso al portal. Aprobá el cliente primero.",
            )
        temp_password = _generate_temp_password()
        portal_user.password_hash = hash_password(temp_password)
        portal_user.must_change_password = True
        self.audit.log(
            actor=actor,
            action="CLIENT_PORTAL_PASSWORD_RESET",
            entity_type="client",
            entity_id=client.id,
        )
        self.db.commit()
        return portal_user.email, temp_password, get_settings().portal_login_url

    def update_profile(
        self,
        *,
        actor: User,
        client: Client,
        ssn: str | None = None,
        date_of_birth=None,
    ) -> Client:
        if ssn:
            client.ssn_encrypted = encrypt_value(ssn)
            self.audit.log(
                actor=actor,
                action="SSN_UPDATED",
                entity_type="client",
                entity_id=client.id,
            )
        if date_of_birth:
            client.date_of_birth = date_of_birth
        self.db.commit()
        self.db.refresh(client)
        return client

    def check_data_complete(self, client: Client) -> bool:
        from app.models.address import Address
        from app.models.document import Document
        from app.models.enums import DocumentType
        from app.models.vehicle import Vehicle

        if not client.ssn_encrypted or not client.date_of_birth:
            return False
        current_addr = self.db.execute(
            select(Address).where(Address.client_id == client.id, Address.type == "CURRENT")
        ).scalar_one_or_none()
        if not current_addr:
            return False
        vehicle = self.db.execute(
            select(Vehicle).where(Vehicle.client_id == client.id, Vehicle.order == 1)
        ).scalar_one_or_none()
        if not vehicle:
            return False

        required_docs = [
            DocumentType.SSN_CARD.value,
            DocumentType.DRIVERS_LICENSE_FRONT.value,
            DocumentType.DRIVERS_LICENSE_BACK.value,
            DocumentType.UTILITY_BILL.value,
        ]
        uploaded_types = {
            d.type
            for d in self.db.execute(select(Document).where(Document.client_id == client.id)).scalars().all()
        }
        if not all(dt in uploaded_types for dt in required_docs):
            return False
        return True

    def on_documents_complete(self, *, client: Client) -> None:
        onboarding = self._get_onboarding_team()
        advisor = self._get_active_advisor(client)
        recipients = onboarding + ([advisor] if advisor else [])
        self.notifications.notify(
            event_type=NotificationEventType.CLIENT_DATA_COMPLETE.value,
            users=recipients,
            title="Cliente completó documentación",
            body=f"{client.full_name} completó la carga de datos y documentos.",
            payload={"client_id": client.id},
        )

    def ensure_board(self, client: Client) -> "Board":
        from app.models.board import Board

        if client.board:
            return client.board
        return self.boards.create_from_template(client)

    def try_create_board(self, *, client: Client) -> None:
        """Crea el tablero si aún no existe (idempotente, sin requisito de documentos)."""
        if client.board:
            return
        self.boards.create_from_template(client)
        self.db.commit()

    def delete_client(self, *, actor: User, client: Client) -> None:
        portal_users = (
            self.db.execute(select(User).where(User.client_id == client.id)).scalars().all()
        )
        for portal_user in portal_users:
            portal_user.client_id = None
            portal_user.is_active = False

        self.audit.log(
            actor=actor,
            action="CLIENT_DELETED",
            entity_type="client",
            entity_id=client.id,
            metadata={"email": client.email},
        )
        self.db.flush()
        self.db.delete(client)
        self.db.commit()

    def _get_onboarding_team(self) -> list[User]:
        return list(
            self.db.execute(
                select(User)
                .join(Role)
                .where(
                    Role.code.in_(["ONBOARDING_MANAGER", "AREA_LEADER", "ADMIN"]),
                    User.is_active.is_(True),
                )
            )
            .scalars()
            .all()
        )

    def _get_active_advisor(self, client: Client) -> User | None:
        for a in client.assignments:
            if a.unassigned_at is None:
                return a.advisor
        return None

    def get_client_for_user(self, user: User, client_id: int) -> Client | None:
        client = (
            self.db.execute(
                select(Client)
                .options(
                    joinedload(Client.assignments),
                    joinedload(Client.addresses),
                    joinedload(Client.vehicles),
                    joinedload(Client.documents),
                    joinedload(Client.board),
                )
                .where(Client.id == client_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if client is None:
            return None
        if user.role.code == "CLIENT" and user.client_id != client_id:
            return None
        if user.role.code == "SALES_REP" and client.registered_by_user_id != user.id:
            return None
        if user.role.code == "ADVISOR":
            advisor = self._get_active_advisor(client)
            if not advisor or advisor.id != user.id:
                return None
        return client
