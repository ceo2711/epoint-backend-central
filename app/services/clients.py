import re
import secrets
import string
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.encryption import decrypt_value, encrypt_value
from app.core.security import hash_password
from app.models.client import Client
from app.models.client_assignment import ClientAssignment
from app.models.enums import ClientStatus, NotificationEventType
from app.models.role import Role
from app.models.user import User
from app.services.audit import AuditService
from app.services.boards import BoardService
from app.core.config import get_settings
from app.core.phone import phones_match
from app.services.email import ClientWelcomeEmailPayload, send_client_welcome_email
from app.services.whatsapp import ClientWelcomeWhatsAppPayload, send_client_welcome_whatsapp
from app.services.notifications import NotificationService
from app.services.notifications.templates import client_approved_in_app_body


def _generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class ClientService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.notifications = NotificationService(db)
        self.audit = AuditService(db)
        self._boards: BoardService | None = None

    @property
    def boards(self) -> BoardService:
        if self._boards is None:
            self._boards = BoardService(self.db)
        return self._boards

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

    def _scoped_clients_query(self, user: User):
        query = select(Client)
        if user.role.code == "SALES_REP":
            query = query.where(Client.registered_by_user_id == user.id)
        elif user.role.code == "ADVISOR":
            query = query.where(
                Client.id.in_(
                    select(ClientAssignment.client_id).where(
                        ClientAssignment.advisor_user_id == user.id,
                        ClientAssignment.unassigned_at.is_(None),
                    )
                )
            )
        return query

    def list_clients_for_user(
        self,
        user: User,
        *,
        page: int,
        page_size: int,
        status_filter: str | None = None,
        search: str | None = None,
        onboarding_only: bool = False,
    ) -> tuple[list[Client], int]:
        from sqlalchemy import func, or_

        query = self._scoped_clients_query(user)
        if onboarding_only:
            query = query.where(Client.approved_at.isnot(None))
        if status_filter:
            query = query.where(Client.status == status_filter)
        if search:
            term = f"%{search}%"
            query = query.where(
                or_(Client.first_name.ilike(term), Client.last_name.ilike(term), Client.email.ilike(term))
            )
        total = self.db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
        clients = (
            self.db.execute(
                query.order_by(Client.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )
            .scalars()
            .all()
        )
        return list(clients), total

    def get_client_stats(self, user: User) -> dict[str, int]:
        from sqlalchemy import func

        pending = ClientStatus.PENDIENTE_DE_REVISION.value
        rejected = ClientStatus.RECHAZADO.value
        completed = ClientStatus.ONBOARDING_COMPLETADO.value
        in_progress = ClientStatus.ONBOARDING_EN_PROGRESO.value
        approved_statuses = {
            ClientStatus.APROBADO_PARA_ONBOARDING.value,
            ClientStatus.EN_CARGA_DATOS.value,
            ClientStatus.DOCUMENTOS_EN_REVISION.value,
            ClientStatus.LISTO_PARA_TABLERO.value,
        }

        scoped = self._scoped_clients_query(user).subquery()
        rows = self.db.execute(
            select(scoped.c.status, func.count()).group_by(scoped.c.status)
        ).all()

        counts: dict[str, int] = {status: count for status, count in rows}
        pending_review = counts.get(pending, 0)
        rejected_count = counts.get(rejected, 0)
        completed_count = counts.get(completed, 0)
        onboarding_in_progress = counts.get(in_progress, 0)
        approved_in_onboarding = sum(counts.get(s, 0) for s in approved_statuses)
        total = sum(counts.values())

        return {
            "pending_review": pending_review,
            "approved_in_onboarding": approved_in_onboarding,
            "rejected": rejected_count,
            "onboarding_in_progress": onboarding_in_progress,
            "completed": completed_count,
            "total": total,
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

        send_client_welcome_email(
            ClientWelcomeEmailPayload(
                recipient_email=client.email,
                first_name=client.first_name,
                temp_password=temp_password,
                portal_login_url=portal_login_url,
                client_id=client.id,
            )
        )

        send_client_welcome_whatsapp(
            ClientWelcomeWhatsAppPayload(
                recipient_phone=client.phone,
                first_name=client.first_name,
                email=client.email,
                temp_password=temp_password,
                portal_login_url=portal_login_url,
                client_id=client.id,
            )
        )

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
            },
            channel_bodies={
                "IN_APP": client_approved_in_app_body(first_name=client.first_name),
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

    @staticmethod
    def format_ssn_display(digits: str) -> str:
        cleaned = re.sub(r"\D", "", digits)
        if len(cleaned) == 9:
            return f"{cleaned[:3]}-{cleaned[3:5]}-{cleaned[5:]}"
        return cleaned

    def get_client_ssn(self, client: Client) -> str:
        if not client.ssn_encrypted:
            raise HTTPException(status_code=404, detail="SSN no registrado")
        try:
            raw = decrypt_value(client.ssn_encrypted)
        except Exception as exc:
            raise HTTPException(status_code=500, detail="No se pudo leer el SSN") from exc
        return self.format_ssn_display(raw)

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

    def get_mentionable_users(
        self,
        *,
        client: Client,
        current_user: User,
        include_client: bool = True,
    ) -> list[User]:
        portal_user = self.db.execute(
            select(User).join(Role).where(User.client_id == client.id, Role.code == "CLIENT", User.is_active.is_(True))
        ).scalar_one_or_none()
        advisor = self._get_active_advisor(client)
        onboarding_team = self._get_onboarding_team()

        candidates: list[User] = []
        if include_client and portal_user:
            candidates.append(portal_user)
        if advisor:
            candidates.append(advisor)
        candidates.extend(onboarding_team)

        seen: set[int] = set()
        unique: list[User] = []
        for user in candidates:
            if user.id != current_user.id and user.id not in seen:
                seen.add(user.id)
                unique.append(user)
        unique.sort(key=lambda row: row.full_name.lower())
        return unique

    def validate_mention_user_ids(
        self,
        *,
        client: Client,
        current_user: User,
        user_ids: list[int],
        is_internal: bool,
    ) -> list[User]:
        if not user_ids:
            return []
        allowed = {
            user.id: user
            for user in self.get_mentionable_users(
                client=client,
                current_user=current_user,
                include_client=not is_internal,
            )
        }
        mentioned: list[User] = []
        seen: set[int] = set()
        for user_id in user_ids:
            user = allowed.get(user_id)
            if user and user_id not in seen:
                seen.add(user_id)
                mentioned.append(user)
        return mentioned

    def get_client_for_user(self, user: User, client_id: int) -> Client | None:
        if not self.user_can_access_client(user, client_id):
            return None
        return self.db.get(Client, client_id)

    def user_can_access_client(self, user: User, client_id: int) -> bool:
        row = self.db.execute(
            select(Client.id, Client.registered_by_user_id).where(Client.id == client_id)
        ).one_or_none()
        if row is None:
            return False
        if user.role.code == "CLIENT":
            return user.client_id == client_id
        if user.role.code == "SALES_REP":
            return row.registered_by_user_id == user.id
        if user.role.code == "ADVISOR":
            assignment = self.db.execute(
                select(ClientAssignment.id).where(
                    ClientAssignment.client_id == client_id,
                    ClientAssignment.advisor_user_id == user.id,
                    ClientAssignment.unassigned_at.is_(None),
                )
            ).scalar_one_or_none()
            return assignment is not None
        return True

    def get_client_detail(self, client_id: int) -> Client | None:
        return (
            self.db.execute(
                select(Client)
                .options(
                    joinedload(Client.assignments).joinedload(ClientAssignment.advisor),
                    joinedload(Client.addresses),
                    joinedload(Client.vehicles),
                    joinedload(Client.documents),
                )
                .where(Client.id == client_id)
            )
            .unique()
            .scalar_one_or_none()
        )
