"""Borrado permanente de empleados. Solo el administrador global."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.constants.default_board_cards import EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL
from app.models.audit_log import AuditLog
from app.models.card_attachment import CardAttachment
from app.models.card_comment import CardComment
from app.models.client import Client
from app.models.client_assignment import ClientAssignment
from app.models.docusign_envelope import DocusignEnvelope
from app.models.influencer import Influencer
from app.models.payment_link import PaymentLink
from app.models.prospect import Prospect
from app.models.prospect_history import ProspectHistory
from app.models.role import Role
from app.models.sent_email import SentEmail
from app.models.user import User
from app.services.role_access import ADMIN_ROLE, is_global_admin
from app.services.storage import get_storage_provider


class StaffUserService:
    def __init__(self, db: Session):
        self.db = db

    def delete_staff_user(self, actor: User, target: User) -> None:
        if not is_global_admin(actor):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo un administrador puede eliminar empleados",
            )
        if target.id == actor.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No puedes eliminar tu propia cuenta",
            )
        if target.role.code == "CLIENT":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
        if target.email.lower() == EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede eliminar la cuenta de sistema",
            )
        if target.role.code == ADMIN_ROLE and self._active_admin_count(exclude_user_id=target.id) < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede eliminar al último administrador activo",
            )

        uid = target.id
        actor_id = actor.id
        avatar_key = target.avatar_storage_key

        # Conservar historial comercial: reasignar FKs NOT NULL / CASCADE al admin.
        self.db.execute(
            update(Client)
            .where(Client.registered_by_user_id == uid)
            .values(registered_by_user_id=actor_id)
        )
        self.db.execute(
            update(Client).where(Client.approved_by_user_id == uid).values(approved_by_user_id=None)
        )
        self.db.execute(
            update(Prospect)
            .where(Prospect.assigned_to_user_id == uid)
            .values(assigned_to_user_id=actor_id)
        )
        self.db.execute(
            update(ProspectHistory)
            .where(ProspectHistory.changed_by_user_id == uid)
            .values(changed_by_user_id=actor_id)
        )
        self.db.execute(
            update(PaymentLink)
            .where(PaymentLink.created_by_user_id == uid)
            .values(created_by_user_id=actor_id)
        )
        self.db.execute(
            update(DocusignEnvelope)
            .where(DocusignEnvelope.sent_by_user_id == uid)
            .values(sent_by_user_id=actor_id)
        )
        self.db.execute(
            update(Influencer)
            .where(Influencer.sales_rep_user_id == uid)
            .values(sales_rep_user_id=actor_id)
        )
        self.db.execute(
            update(CardComment).where(CardComment.author_user_id == uid).values(author_user_id=actor_id)
        )
        self.db.execute(
            update(CardAttachment)
            .where(CardAttachment.uploaded_by_user_id == uid)
            .values(uploaded_by_user_id=actor_id)
        )
        self.db.execute(
            update(ClientAssignment)
            .where(ClientAssignment.assigned_by_user_id == uid)
            .values(assigned_by_user_id=actor_id)
        )
        self.db.execute(delete(ClientAssignment).where(ClientAssignment.advisor_user_id == uid))
        self.db.execute(
            update(SentEmail).where(SentEmail.sent_by_user_id == uid).values(sent_by_user_id=None)
        )
        self.db.execute(
            update(AuditLog).where(AuditLog.actor_user_id == uid).values(actor_user_id=None)
        )
        self.db.execute(update(User).where(User.parent_user_id == uid).values(parent_user_id=None))

        self.db.delete(target)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede eliminar este usuario porque tiene registros vinculados.",
            ) from None

        if avatar_key:
            try:
                get_storage_provider().delete_object(avatar_key)
            except Exception:
                pass

        self.db.commit()

    def _active_admin_count(self, *, exclude_user_id: int) -> int:
        return (
            self.db.execute(
                select(func.count())
                .select_from(User)
                .join(Role)
                .where(
                    Role.code == ADMIN_ROLE,
                    User.is_active.is_(True),
                    User.id != exclude_user_id,
                )
            ).scalar()
            or 0
        )
