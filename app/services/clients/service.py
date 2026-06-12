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
from app.services.notifications import NotificationService


def _generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class ClientService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.notifications = NotificationService(db)
        self.audit = AuditService(db)
        self.boards = BoardService(db)

    def create_client(
        self,
        *,
        actor: User,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
    ) -> Client:
        client = Client(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            email=email.lower().strip(),
            phone=phone.strip(),
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

        existing_user = self.db.execute(select(User).where(User.email == client.email)).scalar_one_or_none()
        if existing_user:
            existing_user.password_hash = hash_password(temp_password)
            existing_user.must_change_password = True
            existing_user.client_id = client.id
            existing_user.is_active = True
            portal_user = existing_user
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

        client.status = ClientStatus.EN_CARGA_DATOS.value

        self.notifications.notify(
            event_type=NotificationEventType.CLIENT_APPROVED.value,
            users=[portal_user],
            title="¡Bienvenido a ePoint!",
            body=(
                f"Hola {client.first_name}, tu cuenta fue aprobada. "
                f"Accedé al portal con tu email y la contraseña temporal enviada. "
                f"Deberás cambiarla en el primer ingreso."
            ),
            payload={"client_id": client.id, "email": client.email},
        )

        self.audit.log(
            actor=actor,
            action="CLIENT_APPROVED",
            entity_type="client",
            entity_id=client.id,
            metadata={"advisor_id": advisor_user_id},
        )
        self.db.commit()
        self.db.refresh(client)
        return client, temp_password

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

    def try_create_board(self, *, client: Client) -> None:
        from app.models.document import Document

        docs = self.db.execute(select(Document).where(Document.client_id == client.id)).scalars().all()
        if not docs or any(d.verification_status != "APROBADO" for d in docs):
            return
        if client.board:
            return
        self.boards.create_from_template(client)
        client.status = ClientStatus.ONBOARDING_EN_PROGRESO.value
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
