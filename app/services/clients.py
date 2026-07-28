import logging
import re
import secrets
import string
from datetime import datetime, timezone

from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.encryption import decrypt_value, encrypt_value
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.card_attachment import CardAttachment
from app.models.card_comment import CardComment
from app.models.client import Client
from app.models.client_assignment import ClientAssignment
from app.models.enums import ClientSource, ClientStatus, NotificationEventType
from app.models.merchant import Merchant
from app.models.notification import Notification
from app.models.password_reset_token import PasswordResetToken
from app.models.prospect import Prospect
from app.models.role import Role
from app.models.session import UserSession
from app.models.user import User
from app.services.audit import AuditService
from app.services.boards import BoardService
from app.services.merchant_context import MerchantContextService
from app.core.config import get_settings
from app.core.phone import phones_match
from app.services.email import ClientWelcomeEmailPayload, send_client_welcome_email
from app.services.whatsapp import ClientWelcomeWhatsAppPayload, send_client_welcome_whatsapp
from app.services.notifications import NotificationService
from app.services.notifications.templates import client_approved_in_app_body, client_approved_in_app_title
from app.services.role_access import SALES_AREA_CODE, is_onboarding_area_leader

if TYPE_CHECKING:
    from app.models.board import Board, BoardTemplate

logger = logging.getLogger(__name__)


def _generate_temp_password(length: int = 12) -> str:
    # Sin # & / ? = : @ — evitan cortes al copiar desde mails/HTML/URLs.
    alphabet = string.ascii_letters + string.digits + "!@$%"
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

    def find_client_with_email(
        self,
        email: str,
        *,
        merchant_id: int | None = None,
        exclude_client_id: int | None = None,
    ) -> Client | None:
        normalized = email.lower().strip()
        query = select(Client).where(Client.email == normalized)
        if merchant_id is not None:
            query = query.where(Client.merchant_id == merchant_id)
        if exclude_client_id is not None:
            query = query.where(Client.id != exclude_client_id)
        return self.db.execute(query).scalar_one_or_none()

    def find_client_with_phone(
        self,
        phone: str,
        *,
        merchant_id: int | None = None,
        exclude_client_id: int | None = None,
    ) -> Client | None:
        settings = get_settings()
        country_code = settings.whatsapp_default_country_code
        query = select(Client)
        if merchant_id is not None:
            query = query.where(Client.merchant_id == merchant_id)
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

    def _scoped_clients_query(
        self,
        user: User,
        merchant_id: int | None = None,
        *,
        all_merchants: bool = False,
        filter_sede_id: int | None = None,
    ):
        from app.services.sede_scope import effective_sede_id

        query = select(Client)
        if all_merchants:
            accessible = MerchantContextService(self.db).list_accessible_merchants(user)
            merchant_ids = [merchant.id for merchant in accessible]
            if merchant_ids:
                query = query.where(Client.merchant_id.in_(merchant_ids))
            else:
                query = query.where(Client.id == -1)
        elif merchant_id is not None:
            query = query.where(Client.merchant_id == merchant_id)

        sede_id = effective_sede_id(user)
        if sede_id is not None:
            query = query.where(Client.sede_id == sede_id)
        elif filter_sede_id is not None:
            query = query.where(Client.sede_id == filter_sede_id)

        if user.role.code == "SALES_REP":
            from app.services.sub_sellers import SubSellerService

            team_ids = SubSellerService(self.db).list_team_user_ids(user)
            query = query.where(Client.registered_by_user_id.in_(team_ids))
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
        merchant_id: int | None = None,
        all_merchants: bool = False,
        filter_sede_id: int | None = None,
        page: int,
        page_size: int,
        status_filter: str | None = None,
        search: str | None = None,
        onboarding_only: bool = False,
        sales_rep_id: int | None = None,
    ) -> tuple[list[Client], int]:
        from sqlalchemy import func, or_

        query = self._scoped_clients_query(
            user,
            merchant_id,
            all_merchants=all_merchants,
            filter_sede_id=filter_sede_id,
        )
        if onboarding_only:
            query = query.where(
                or_(
                    Client.status == ClientStatus.PENDIENTE_DE_REVISION.value,
                    Client.status == ClientStatus.RECHAZADO.value,
                    Client.approved_at.isnot(None),
                )
            )
        if sales_rep_id is not None:
            if user.role.code == "SALES_REP" and sales_rep_id != user.id:
                from app.services.sub_sellers import SubSellerService

                team_ids = SubSellerService(self.db).list_team_user_ids(user)
                if sales_rep_id not in team_ids:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
            query = query.where(Client.registered_by_user_id == sales_rep_id)
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
                query.options(
                    joinedload(Client.merchant),
                    joinedload(Client.registered_by),
                    joinedload(Client.assignments).joinedload(ClientAssignment.advisor),
                )
                .order_by(Client.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .unique()
            .scalars()
            .all()
        )
        return list(clients), total

    def get_client_stats(
        self,
        user: User,
        *,
        merchant_id: int | None = None,
        all_merchants: bool = False,
        filter_sede_id: int | None = None,
    ) -> dict[str, int]:
        from sqlalchemy import func

        pending = ClientStatus.PENDIENTE_DE_REVISION.value
        rejected = ClientStatus.RECHAZADO.value
        completed = ClientStatus.ONBOARDING_COMPLETADO.value
        in_progress = ClientStatus.ONBOARDING_EN_PROGRESO.value
        approved_statuses = {
            ClientStatus.APROBADO_PARA_ONBOARDING.value,
            ClientStatus.EN_CARGA_DATOS.value,
            ClientStatus.DOCUMENTOS_EN_REVISION.value,
            ClientStatus.LISTO_PARA_TRABAJAR.value,
        }

        scoped = self._scoped_clients_query(
            user,
            merchant_id,
            all_merchants=all_merchants,
            filter_sede_id=filter_sede_id,
        ).subquery()
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

    def assert_email_available(
        self,
        email: str,
        *,
        merchant_id: int | None = None,
        exclude_client_id: int | None = None,
    ) -> None:
        duplicate = self.find_client_with_email(
            email,
            merchant_id=merchant_id,
            exclude_client_id=exclude_client_id,
        )
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El email ya está registrado por {duplicate.full_name} (cliente #{duplicate.id})",
            )

    def assert_phone_available(
        self,
        phone: str,
        *,
        merchant_id: int | None = None,
        exclude_client_id: int | None = None,
    ) -> None:
        duplicate = self.find_client_with_phone(
            phone,
            merchant_id=merchant_id,
            exclude_client_id=exclude_client_id,
        )
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
        merchant_id: int | None = None,
        exclude_client_id: int | None = None,
    ) -> dict:
        result: dict = {"available": True, "email": None, "phone": None}
        if email and "@" in email:
            duplicate = self.find_client_with_email(
                email,
                merchant_id=merchant_id,
                exclude_client_id=exclude_client_id,
            )
            if duplicate:
                result["available"] = False
                result["email"] = self._conflict_payload(duplicate)
        if phone and len(phone.strip()) >= 5:
            duplicate = self.find_client_with_phone(
                phone,
                merchant_id=merchant_id,
                exclude_client_id=exclude_client_id,
            )
            if duplicate:
                result["available"] = False
                result["phone"] = self._conflict_payload(duplicate)
        return result

    def _get_active_merchant(self, merchant_id: int) -> Merchant:
        merchant = self.db.get(Merchant, merchant_id)
        if merchant is None or not merchant.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Merchant no válido o inactivo")
        return merchant

    def _resolve_default_merchant(self) -> Merchant | None:
        return self.db.execute(
            select(Merchant).where(Merchant.is_active.is_(True)).order_by(Merchant.id).limit(1)
        ).scalar_one_or_none()

    def create_client(
        self,
        *,
        actor: User,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        source: str | None = None,
        merchant_id: int | None = None,
        default_merchant_id: int | None = None,
        is_qualified: bool = True,
    ) -> Client:
        normalized_email = email.lower().strip()
        normalized_phone = phone.strip()

        resolved_source = source or ClientSource.OTHER.value
        merchant_ctx = MerchantContextService(self.db)
        if merchant_id is not None:
            if not merchant_ctx.user_can_access_merchant(actor, merchant_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tenés acceso a ese comercio",
                )
            merchant = self._get_active_merchant(merchant_id)
        elif default_merchant_id is not None:
            if not merchant_ctx.user_can_access_merchant(actor, default_merchant_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tenés acceso al comercio activo",
                )
            merchant = self._get_active_merchant(default_merchant_id)
        else:
            merchant = self._resolve_default_merchant()
            if merchant is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No hay merchants activos configurados",
                )

        self.assert_email_available(normalized_email, merchant_id=merchant.id)
        self.assert_phone_available(normalized_phone, merchant_id=merchant.id)

        client = Client(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            email=normalized_email,
            phone=normalized_phone,
            source=resolved_source,
            merchant_id=merchant.id,
            sede_id=merchant.sede_id,
            registered_by_user_id=actor.id,
            status=ClientStatus.PENDIENTE_DE_REVISION.value,
            is_qualified=bool(is_qualified),
        )
        self.db.add(client)
        self.db.flush()

        self.audit.log(
            actor=actor,
            action="CLIENT_CREATED",
            entity_type="client",
            entity_id=client.id,
        )

        portal_temp_password = self.try_auto_approve_pending_client(
            actor=actor,
            client=client,
            commit=False,
        )
        if portal_temp_password is None:
            onboarding_users = self._get_onboarding_team()
            self.notifications.notify(
                event_type=NotificationEventType.NEW_CLIENT_PENDING_REVIEW.value,
                users=onboarding_users,
                title="Nuevo cliente para revisar",
                body=f"{client.full_name} fue registrado y espera revisión.",
                payload={"client_id": client.id},
            )

        self.db.commit()
        self.db.refresh(client)
        if portal_temp_password is not None:
            self._send_client_portal_welcome(client, portal_temp_password)
        return client

    def update_client(
        self,
        *,
        actor: User,
        client: Client,
        **fields,
    ) -> Client:
        if actor.role.code == "SALES_REP" and client.status not in (
            ClientStatus.PENDIENTE_DE_REVISION.value,
            ClientStatus.RECHAZADO.value,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Solo puede editar clientes pendientes o rechazados",
            )
        ssn = fields.pop("ssn", None)
        date_of_birth = fields.pop("date_of_birth", None)
        if "email" in fields and fields["email"] is not None:
            self.assert_email_available(
                fields["email"],
                merchant_id=client.merchant_id,
                exclude_client_id=client.id,
            )
        if "phone" in fields and fields["phone"] is not None:
            self.assert_phone_available(
                fields["phone"],
                merchant_id=client.merchant_id,
                exclude_client_id=client.id,
            )
        if "merchant_id" in fields and fields["merchant_id"] is not None:
            self._get_active_merchant(fields["merchant_id"])
        if "source" in fields and fields["source"] is not None:
            fields["source"] = str(fields["source"])
        for key, value in fields.items():
            if value is not None and hasattr(client, key):
                if key == "email" and value:
                    setattr(client, key, value.lower().strip())
                elif isinstance(value, str):
                    setattr(client, key, value.strip())
                else:
                    setattr(client, key, value)
        if ssn:
            client.ssn_encrypted = encrypt_value(ssn)
            self.audit.log(
                actor=actor,
                action="SSN_UPDATED",
                entity_type="client",
                entity_id=client.id,
            )
        if date_of_birth is not None:
            client.date_of_birth = date_of_birth
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
        portal_temp_password = self.try_auto_approve_pending_client(
            actor=actor,
            client=client,
            commit=False,
        )
        if portal_temp_password is None:
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
        if portal_temp_password is not None:
            self._send_client_portal_welcome(client, portal_temp_password)
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

    def _clear_portal_auth_state(self, portal_user: User) -> None:
        """Limpia 2FA, sesiones y tokens para que el portal arranque desde cero."""
        portal_user.totp_enabled = False
        portal_user.totp_secret_encrypted = None
        portal_user.totp_confirmed_at = None
        portal_user.must_change_password = True
        self.db.execute(delete(UserSession).where(UserSession.user_id == portal_user.id))
        self.db.execute(
            delete(PasswordResetToken).where(PasswordResetToken.user_id == portal_user.id)
        )

    def _purge_portal_user(self, portal_user: User) -> None:
        """Elimina por completo el usuario del portal (2FA, sesiones, notificaciones, etc.)."""
        uid = portal_user.id
        # Limpiar 2FA antes del DELETE por si alguna FK falla a mitad de camino.
        portal_user.totp_enabled = False
        portal_user.totp_secret_encrypted = None
        portal_user.totp_confirmed_at = None
        self.db.execute(delete(Notification).where(Notification.user_id == uid))
        self.db.execute(delete(UserSession).where(UserSession.user_id == uid))
        self.db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == uid))
        self.db.execute(delete(CardComment).where(CardComment.author_user_id == uid))
        self.db.execute(delete(CardAttachment).where(CardAttachment.uploaded_by_user_id == uid))
        self.db.execute(
            update(AuditLog)
            .where(AuditLog.actor_user_id == uid)
            .values(actor_user_id=None)
        )
        self.db.delete(portal_user)

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
                    select(User)
                    .options(joinedload(User.role))
                    .where(func.lower(User.email) == client.email.lower())
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
                    totp_enabled=False,
                    totp_secret_encrypted=None,
                    totp_confirmed_at=None,
                    is_active=True,
                )
                self.db.add(portal_user)
                self.db.flush()
                return portal_user

        portal_user.password_hash = hash_password(temp_password)
        portal_user.client_id = client.id
        portal_user.is_active = True
        portal_user.first_name = client.first_name
        portal_user.last_name = client.last_name
        portal_user.phone = client.phone
        portal_user.role_id = client_role.id
        self._clear_portal_auth_state(portal_user)
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

    def pick_least_loaded_advisor(self) -> User | None:
        """Elige el asesor activo con menos clientes asignados (desempate por id)."""
        advisors = list(
            self.db.execute(
                select(User)
                .join(Role)
                .options(joinedload(User.role))
                .where(Role.code == "ADVISOR", User.is_active.is_(True))
                .order_by(User.id)
            )
            .unique()
            .scalars()
            .all()
        )
        if not advisors:
            return None

        load_rows = self.db.execute(
            select(ClientAssignment.advisor_user_id, func.count())
            .where(ClientAssignment.unassigned_at.is_(None))
            .group_by(ClientAssignment.advisor_user_id)
        ).all()
        load_by_advisor = {int(advisor_id): int(count) for advisor_id, count in load_rows}

        return min(advisors, key=lambda user: (load_by_advisor.get(user.id, 0), user.id))

    def try_auto_approve_pending_client(
        self,
        *,
        actor: User,
        client: Client,
        commit: bool = True,
    ) -> str | None:
        """Revisa datos mínimos y aprueba automáticamente.

        Returns:
            Contraseña temporal si se aprobó; ``None`` si no aplicó auto-aprobación.
            Con ``commit=False`` el caller debe enviar el welcome **después** de su commit.
        """
        if client.status != ClientStatus.PENDIENTE_DE_REVISION.value:
            return None

        from app.services.chatbot.approval_rules import validate_approval_requirements

        issues = validate_approval_requirements(client, self)
        if issues:
            logger.info(
                "Auto-aprobación omitida para cliente #%s: %s",
                client.id,
                "; ".join(issues),
            )
            return None

        _client, temp_password = self.approve_client(
            actor=actor,
            client=client,
            # Con commit=False el welcome lo dispara el caller tras persistir.
            send_welcome_notifications=commit,
            commit=commit,
        )
        logger.info("Cliente #%s auto-aprobado (asesor se asignará al completar docs)", client.id)
        return temp_password

    def _send_client_portal_welcome(self, client: Client, temp_password: str) -> None:
        """Email + WhatsApp con credenciales. Llamar solo después de un commit exitoso."""
        settings = get_settings()
        portal_login_url = settings.portal_login_url
        merchant_name: str | None = None
        if client.merchant_id:
            merchant_row = self.db.get(Merchant, client.merchant_id)
            merchant_name = merchant_row.name if merchant_row else None

        send_client_welcome_email(
            ClientWelcomeEmailPayload(
                recipient_email=client.email,
                first_name=client.first_name,
                temp_password=temp_password,
                portal_login_url=portal_login_url,
                client_id=client.id,
                merchant_name=merchant_name,
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

    def approve_client(
        self,
        *,
        actor: User,
        client: Client,
        send_welcome_notifications: bool = True,
        commit: bool = True,
        board_template: "BoardTemplate | None" = None,
        advisor_user_id: int | None = None,
    ) -> tuple[Client, str]:
        """Aprueba al cliente para onboarding. No asigna asesor ni crea tablero todavía.

        El asesor y el tablero se asignan al pasar a LISTO_PARA_TRABAJAR
        (datos + documentos verificados).
        `advisor_user_id` se ignora (compatibilidad con clientes/API antiguos).

        Las credenciales por email/WhatsApp se envían **después** del commit
        (si ``commit=True``). Con ``commit=False``, el caller debe llamar
        ``_send_client_portal_welcome`` tras persistir.
        """
        del board_template, advisor_user_id  # compat / no usados en approve

        if client.status != ClientStatus.PENDIENTE_DE_REVISION.value:
            raise HTTPException(status_code=400, detail="Solo clientes pendientes pueden aprobarse")

        client.status = ClientStatus.APROBADO_PARA_ONBOARDING.value
        client.approved_at = datetime.now(timezone.utc)
        client.approved_by_user_id = actor.id

        temp_password = _generate_temp_password()
        client_role = self.db.execute(select(Role).where(Role.code == "CLIENT")).scalar_one()
        portal_user = self._resolve_portal_user(client, client_role, temp_password)
        client.portal_temp_password_encrypted = encrypt_value(temp_password)

        client.status = ClientStatus.EN_CARGA_DATOS.value

        self.notifications.mark_client_events_read(
            client_id=client.id,
            event_types=[NotificationEventType.NEW_CLIENT_PENDING_REVIEW.value],
        )

        settings = get_settings()
        portal_login_url = settings.portal_login_url

        self.notifications.notify(
            event_type=NotificationEventType.CLIENT_APPROVED.value,
            users=[portal_user],
            title=client_approved_in_app_title(),
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
            commit=commit,
        )

        self.audit.log(
            actor=actor,
            action="CLIENT_APPROVED",
            entity_type="client",
            entity_id=client.id,
            metadata={},
        )
        if commit:
            self.db.commit()
            self.db.refresh(client)
            if send_welcome_notifications:
                self._send_client_portal_welcome(client, temp_password)
            else:
                logger.info(
                    "Welcome email/WhatsApp omitidos para cliente #%s (%s) — aprobación masiva",
                    client.id,
                    client.email,
                )
        else:
            self.db.flush()
            if send_welcome_notifications:
                logger.warning(
                    "Welcome diferido para cliente #%s — commit=False; el caller debe enviar tras persistir",
                    client.id,
                )
        return client, temp_password

    def promote_to_ready_to_work(self, client: Client) -> User | None:
        """Marca Listo para trabajar, asigna asesor si falta y crea el tablero.

        Se llama cuando datos + documentos requeridos están verificados con éxito.
        No hace commit.
        """
        client.status = ClientStatus.LISTO_PARA_TRABAJAR.value

        advisor: User | None = None
        active = self._get_active_advisors(client)
        if active:
            advisor = active[0]
        else:
            advisor = self.pick_least_loaded_advisor()
            if advisor is None:
                logger.warning(
                    "Cliente #%s listo para trabajar sin asesores activos disponibles",
                    client.id,
                )
            else:
                assigned_by = client.approved_by_user_id or advisor.id
                self.db.add(
                    ClientAssignment(
                        client_id=client.id,
                        advisor_user_id=advisor.id,
                        assigned_by_user_id=assigned_by,
                    )
                )
                self.audit.log(
                    actor=None,
                    action="CLIENT_ADVISOR_AUTO_ASSIGNED",
                    entity_type="client",
                    entity_id=client.id,
                    metadata={"advisor_id": advisor.id, "trigger": "LISTO_PARA_TRABAJAR"},
                )
                logger.info(
                    "Cliente #%s listo para trabajar → asesor #%s (%s)",
                    client.id,
                    advisor.id,
                    advisor.email,
                )

        try:
            self.try_create_board(client=client)
        except Exception:
            logger.exception(
                "No se pudo crear el tablero al pasar cliente #%s a LISTO_PARA_TRABAJAR",
                client.id,
            )

        return advisor

    def bulk_approve_clients(
        self,
        *,
        actor: User,
        clients: list[Client],
        send_welcome_notifications: bool = False,
        advisor_user_id: int | None = None,
    ) -> tuple[list[tuple[Client, str]], list[tuple[Client, str]]]:
        """Aprueba varios clientes en una sola transacción (más rápido que uno por uno)."""
        del advisor_user_id  # compat: ya no se asigna asesor en approve
        if not clients:
            return [], []

        successes: list[tuple[Client, str]] = []
        failures: list[tuple[Client, str]] = []

        for client in clients:
            if client.status != ClientStatus.PENDIENTE_DE_REVISION.value:
                failures.append((client, "Solo clientes pendientes pueden aprobarse"))
                continue
            try:
                approved_client, temp_password = self.approve_client(
                    actor=actor,
                    client=client,
                    send_welcome_notifications=send_welcome_notifications,
                    commit=False,
                )
                successes.append((approved_client, temp_password))
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                failures.append((client, detail))

        if successes:
            self.db.commit()
            for client, temp_password in successes:
                self.db.refresh(client)
                if send_welcome_notifications:
                    self._send_client_portal_welcome(client, temp_password)
        elif failures:
            self.db.rollback()

        return successes, failures

    def reassign_advisor(
        self,
        *,
        actor: User,
        client: Client,
        advisor_user_id: int,
    ) -> User:
        """Reemplaza todos los asesores activos por uno solo (compat / onboarding)."""
        if client.approved_at is None:
            raise HTTPException(
                status_code=400,
                detail="Solo clientes aprobados pueden tener asesor asignado",
            )

        advisor = self.db.get(User, advisor_user_id)
        if advisor is None or advisor.role.code != "ADVISOR" or not advisor.is_active:
            raise HTTPException(status_code=400, detail="Asesor inválido")

        current_ids = {a.id for a in self._get_active_advisors(client)}
        if current_ids == {advisor_user_id}:
            return advisor

        now = datetime.now(timezone.utc)
        for assignment in client.assignments:
            if assignment.unassigned_at is None:
                assignment.unassigned_at = now

        self.db.add(
            ClientAssignment(
                client_id=client.id,
                advisor_user_id=advisor_user_id,
                assigned_by_user_id=actor.id,
            )
        )
        self.audit.log(
            actor=actor,
            action="CLIENT_ADVISOR_REASSIGNED",
            entity_type="client",
            entity_id=client.id,
            metadata={"advisor_id": advisor_user_id},
        )
        self.db.commit()
        self.db.refresh(client)
        return advisor

    def add_advisor(
        self,
        *,
        actor: User,
        client: Client,
        advisor_user_id: int,
    ) -> User:
        if client.approved_at is None:
            raise HTTPException(
                status_code=400,
                detail="Solo clientes aprobados pueden tener asesor asignado",
            )

        advisor = self.db.get(User, advisor_user_id)
        if advisor is None or advisor.role.code != "ADVISOR" or not advisor.is_active:
            raise HTTPException(status_code=400, detail="Asesor inválido")

        active = self._get_active_advisors(client)
        if any(row.id == advisor_user_id for row in active):
            return advisor

        self.db.add(
            ClientAssignment(
                client_id=client.id,
                advisor_user_id=advisor_user_id,
                assigned_by_user_id=actor.id,
            )
        )
        self.audit.log(
            actor=actor,
            action="CLIENT_ADVISOR_ADDED",
            entity_type="client",
            entity_id=client.id,
            metadata={"advisor_id": advisor_user_id},
        )
        self.db.commit()
        return advisor

    def _client_requires_advisor(self, client: Client) -> bool:
        """A partir de Listo para trabajar el cliente debe conservar al menos un asesor."""
        return client.status in {
            ClientStatus.LISTO_PARA_TRABAJAR.value,
            ClientStatus.ONBOARDING_EN_PROGRESO.value,
            ClientStatus.ONBOARDING_COMPLETADO.value,
        }

    def remove_advisor(
        self,
        *,
        actor: User,
        client: Client,
        advisor_user_id: int,
    ) -> None:
        if client.approved_at is None:
            raise HTTPException(
                status_code=400,
                detail="Solo clientes aprobados pueden tener asesor asignado",
            )

        active = [
            assignment
            for assignment in client.assignments
            if assignment.unassigned_at is None
        ]
        target = next((row for row in active if row.advisor_user_id == advisor_user_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="El asesor no está asignado a este cliente")

        if len(active) <= 1 and self._client_requires_advisor(client):
            raise HTTPException(
                status_code=400,
                detail="El cliente debe conservar al menos un asesor asignado",
            )

        target.unassigned_at = datetime.now(timezone.utc)
        self.audit.log(
            actor=actor,
            action="CLIENT_ADVISOR_REMOVED",
            entity_type="client",
            entity_id=client.id,
            metadata={"advisor_id": advisor_user_id},
        )
        self.db.commit()

    def actor_can_manage_client_advisors(self, actor: User, client: Client) -> bool:
        role = actor.role.code if actor.role else None
        if role in {"ONBOARDING_MANAGER", "ADMIN", "BRANCH_MANAGER"}:
            return True
        if is_onboarding_area_leader(actor):
            return True
        if role == "ADVISOR":
            return any(
                assignment.unassigned_at is None and assignment.advisor_user_id == actor.id
                for assignment in client.assignments
            )
        return False

    def require_can_manage_client_advisors(self, actor: User, client: Client) -> None:
        if not self.actor_can_manage_client_advisors(actor, client):
            raise HTTPException(
                status_code=403,
                detail="Solo onboarding o un asesor asignado pueden gestionar los asesores del cliente",
            )

    def get_stored_portal_temp_password(self, client: Client) -> str | None:
        """Devuelve la contraseña de portal recuperable (temporal o la última conocida)."""
        if not client.portal_temp_password_encrypted:
            return None

        try:
            return decrypt_value(client.portal_temp_password_encrypted)
        except Exception:
            logger.exception(
                "No se pudo descifrar la contraseña del portal para cliente #%s", client.id
            )
            return None

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
        client.portal_temp_password_encrypted = encrypt_value(temp_password)
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

        from app.services.document_requirements import is_upload_requirement_met

        uploaded_types = {
            d.type
            for d in self.db.execute(select(Document).where(Document.client_id == client.id)).scalars().all()
        }
        if not is_upload_requirement_met(uploaded_types):
            return False
        return True

    def on_documents_complete(self, *, client: Client) -> None:
        onboarding = self._get_onboarding_team()
        advisors = self._get_active_advisors(client)
        recipients = onboarding + advisors
        self.notifications.notify(
            event_type=NotificationEventType.CLIENT_DATA_COMPLETE.value,
            users=recipients,
            title="Cliente completó documentación",
            body=f"{client.full_name} completó la carga de datos y documentos.",
            payload={"client_id": client.id},
        )

    def ensure_board(self, client: Client, board_template: "BoardTemplate | None" = None) -> "Board":
        from app.models.board import Board

        if client.board:
            return client.board
        return self.boards.create_from_template(client, template=board_template)

    def try_create_board(self, *, client: Client) -> None:
        """Crea el tablero si aún no existe (idempotente, sin requisito de documentos)."""
        if client.board:
            return
        self.boards.create_from_template(client)
        self.db.commit()

    def delete_client(self, *, actor: User, client: Client) -> None:
        """Borrado definitivo (solo ADMIN vía permiso clients:delete): elimina el cliente
        y también los usuarios del portal asociados (incluido 2FA, sesiones y tokens),
        sin dejar rastros que bloqueen volver a registrar el mismo email/teléfono."""
        portal_users = list(
            self.db.execute(select(User).where(User.client_id == client.id)).scalars().all()
        )
        email_matches = list(
            self.db.execute(
                select(User)
                .join(Role)
                .where(
                    Role.code == "CLIENT",
                    func.lower(User.email) == client.email.lower(),
                )
            )
            .scalars()
            .all()
        )
        users_to_purge = list({user.id: user for user in (*portal_users, *email_matches)}.values())

        source_prospects = list(
            self.db.execute(
                select(Prospect).where(Prospect.converted_client_id == client.id)
            )
            .scalars()
            .all()
        )

        self.audit.log(
            actor=actor,
            action="CLIENT_DELETED",
            entity_type="client",
            entity_id=client.id,
            metadata={
                "email": client.email,
                "purged_portal_user_ids": [u.id for u in users_to_purge],
                "purged_prospect_ids": [p.id for p in source_prospects],
            },
        )

        # Desvincular portal users antes del DELETE del cliente.
        for portal_user in users_to_purge:
            portal_user.client_id = None
        self.db.flush()

        # El prospecto origen vuelve a listarse si solo se hace SET NULL:
        # hay que eliminarlo junto con el cliente.
        for prospect in source_prospects:
            self.db.delete(prospect)
        self.db.flush()

        # Documentos, tablero, comentarios y adjuntos se eliminan en cascada.
        self.db.delete(client)
        self.db.flush()

        for portal_user in users_to_purge:
            self._purge_portal_user(portal_user)
        self.db.commit()

    def bulk_delete_clients(self, *, actor: User, client_ids: list[int]) -> dict[str, list]:
        deleted_ids: list[int] = []
        failures: list[dict[str, int | str]] = []
        unique_ids = list(dict.fromkeys(client_ids))

        for client_id in unique_ids:
            if not self.user_can_access_client(actor, client_id, merchant_id=None):
                failures.append({"client_id": client_id, "reason": "No autorizado"})
                continue
            client = self.db.get(Client, client_id)
            if client is None:
                failures.append({"client_id": client_id, "reason": "Cliente no encontrado"})
                continue
            try:
                self.delete_client(actor=actor, client=client)
                deleted_ids.append(client_id)
            except HTTPException as exc:
                self.db.rollback()
                detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                failures.append({"client_id": client_id, "reason": detail})
            except Exception as exc:
                self.db.rollback()
                logger.exception("Error eliminando cliente #%s", client_id)
                reason = str(getattr(exc, "orig", None) or exc)
                if len(reason) > 180:
                    reason = f"{reason[:177]}..."
                failures.append({"client_id": client_id, "reason": reason or "No se pudo eliminar el cliente"})

        return {"deleted_ids": deleted_ids, "failures": failures}

    def _get_onboarding_team(self) -> list[User]:
        """Staff notificado en onboarding (excluye líderes del área de ventas)."""
        users = list(
            self.db.execute(
                select(User)
                .join(Role)
                .options(joinedload(User.area), joinedload(User.role))
                .where(
                    Role.code.in_(["ONBOARDING_MANAGER", "AREA_LEADER", "ADMIN", "BRANCH_MANAGER"]),
                    User.is_active.is_(True),
                )
            )
            .unique()
            .scalars()
            .all()
        )
        return [
            user
            for user in users
            if not (
                user.role.code == "AREA_LEADER"
                and user.area is not None
                and user.area.code == SALES_AREA_CODE
            )
        ]

    def _get_mentionable_onboarding(self, client: Client) -> list[User]:
        """Solo ONBOARDING_MANAGER (sin admin/gerente). Preferir la misma sede del cliente."""
        users = list(
            self.db.execute(
                select(User)
                .join(Role)
                .options(joinedload(User.role))
                .where(Role.code == "ONBOARDING_MANAGER", User.is_active.is_(True))
            )
            .unique()
            .scalars()
            .all()
        )
        sede_id = client.sede_id
        if sede_id is not None:
            scoped = [user for user in users if user.sede_id == sede_id]
            if scoped:
                return scoped
        return users

    def _get_active_advisor(self, client: Client) -> User | None:
        advisors = self._get_active_advisors(client)
        return advisors[0] if advisors else None

    def _get_active_advisors(self, client: Client) -> list[User]:
        advisors: list[User] = []
        seen: set[int] = set()
        for assignment in client.assignments:
            if assignment.unassigned_at is not None:
                continue
            advisor = assignment.advisor
            if advisor is None or advisor.id in seen:
                continue
            seen.add(advisor.id)
            advisors.append(advisor)
        return advisors

    def get_mentionable_users(
        self,
        *,
        client: Client,
        current_user: User,
        include_client: bool = True,
    ) -> list[User]:
        """Participantes del hilo del cliente: portal + asesores asignados + onboarding de la sede."""
        portal_user = self.db.execute(
            select(User)
            .join(Role)
            .options(joinedload(User.role))
            .where(User.client_id == client.id, Role.code == "CLIENT", User.is_active.is_(True))
        ).scalar_one_or_none()
        advisors = self._get_active_advisors(client)
        onboarding = self._get_mentionable_onboarding(client)

        candidates: list[User] = []
        if include_client and portal_user:
            candidates.append(portal_user)
        candidates.extend(advisors)
        candidates.extend(onboarding)

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
            if user_id == current_user.id:
                continue
            user = allowed.get(user_id)
            if user and user_id not in seen:
                seen.add(user_id)
                mentioned.append(user)
        return mentioned

    def get_client_for_user(
        self,
        user: User,
        client_id: int,
        *,
        merchant_id: int | None = None,
    ) -> Client | None:
        if not self.user_can_access_client(user, client_id, merchant_id=merchant_id):
            return None
        return self.db.get(Client, client_id)

    def user_can_access_client(
        self,
        user: User,
        client_id: int,
        *,
        merchant_id: int | None = None,
    ) -> bool:
        from app.services.sede_scope import effective_sede_id

        row = self.db.execute(
            select(
                Client.id,
                Client.registered_by_user_id,
                Client.merchant_id,
                Client.sede_id,
            ).where(Client.id == client_id)
        ).one_or_none()
        if row is None:
            return False
        client_merchant_id = row.merchant_id
        merchant_ctx = MerchantContextService(self.db)
        if client_merchant_id is not None:
            if not merchant_ctx.user_can_access_merchant(user, client_merchant_id):
                return False
        elif merchant_id is not None and not merchant_ctx.user_can_access_merchant(user, merchant_id):
            return False

        sede_id = effective_sede_id(user)
        if sede_id is not None and row.sede_id != sede_id:
            return False

        if user.role.code == "CLIENT":
            return user.client_id == client_id
        if user.role.code == "SALES_REP":
            from app.services.sub_sellers import SubSellerService

            team_ids = SubSellerService(self.db).list_team_user_ids(user)
            return row.registered_by_user_id in team_ids
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

    def user_can_view_client_onboarding_data(self, user: User, client_id: int) -> bool:
        """Documentos, perfil extendido, portal, tablero: admin, gerente, onboarding, líder onboarding y asesor asignado."""
        if user.role.code in ("ADMIN", "BRANCH_MANAGER", "ONBOARDING_MANAGER"):
            return self.user_can_access_client(user, client_id)
        if is_onboarding_area_leader(user):
            return self.user_can_access_client(user, client_id)
        if user.role.code == "ADVISOR":
            return self.user_can_access_client(user, client_id)
        return False

    def user_can_view_approved_client_workspace(
        self,
        user: User,
        client_id: int,
        *,
        client: Client | None = None,
    ) -> bool:
        """Workspace completo post-aprobación: datos extendidos, documentos, tablero."""
        row = client if client is not None else self.db.get(Client, client_id)
        if row is None or row.approved_at is None:
            return False
        return self.user_can_view_client_onboarding_data(user, client_id)

    def get_client_detail(self, client_id: int) -> Client | None:
        return (
            self.db.execute(
                select(Client)
                .options(
                    joinedload(Client.merchant),
                    joinedload(Client.registered_by),
                    joinedload(Client.docusign_envelope),
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
