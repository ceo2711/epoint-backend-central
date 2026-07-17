from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models.calendly_event import CalendlyEvent
from app.models.client import Client
from app.models.docusign_envelope import DocusignEnvelope
from app.models.enums import (
    ClientSource,
    ProspectHistoryEventType,
    ProspectStatus,
)
from app.models.merchant import Merchant
from app.models.payment_link import PaymentLink, PaymentLinkStatus
from app.models.prospect import Prospect
from app.models.prospect_history import ProspectHistory
from app.models.user import User
from app.services.audit import AuditService
from app.services.clients import ClientService
from app.services.email.client_conversion_welcome import (
    ClientConversionWelcomeEmailPayload,
    send_client_conversion_welcome_email,
)
from app.services.merchant_context import MerchantContextService

logger = logging.getLogger(__name__)

INITIAL_STATUS = ProspectStatus.PENDIENTE_CONTACTAR.value

SALES_REP_MANUAL_STATUSES = {ProspectStatus.LEAD_CERRADO.value}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ProspectStatus.PENDIENTE_CONTACTAR.value: {
        ProspectStatus.LEAD_CONTACTADO.value,
        ProspectStatus.LEAD_CERRADO.value,
    },
    ProspectStatus.LEAD_CONTACTADO.value: {
        ProspectStatus.PENDIENTE_CONTACTAR.value,
        ProspectStatus.CONTRATO_ENVIADO.value,
        ProspectStatus.LEAD_CERRADO.value,
    },
    ProspectStatus.CONTRATO_ENVIADO.value: {
        ProspectStatus.PAGO_COMPLETADO.value,
        ProspectStatus.LEAD_CERRADO.value,
    },
    ProspectStatus.PAGO_COMPLETADO.value: set(),
    ProspectStatus.LEAD_CERRADO.value: set(),
}

MEETING_COMPLETE_STATUSES = frozenset({
    ProspectStatus.LEAD_CONTACTADO.value,
    ProspectStatus.CONTRATO_ENVIADO.value,
    ProspectStatus.PAGO_COMPLETADO.value,
})


class ProspectService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuditService(db)
        self.merchant_ctx = MerchantContextService(db)

    def list_prospects(
        self,
        user: User,
        *,
        merchant_id: int | None = None,
        all_merchants: bool = False,
        sales_rep_id: int | None = None,
        status_filter: str | None = None,
        search: str | None = None,
        include_converted: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Prospect], int]:
        query = self._scoped_query(user, merchant_id, all_merchants=all_merchants)
        if not include_converted:
            query = query.where(Prospect.converted_client_id.is_(None))
        if sales_rep_id is not None:
            if user.role.code == "SALES_REP" and sales_rep_id != user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
            query = query.where(Prospect.assigned_to_user_id == sales_rep_id)
        if status_filter:
            query = query.where(Prospect.status == status_filter)
        if search:
            words = [part.strip() for part in search.strip().split() if part.strip()]
            for word in words:
                term = f"%{word}%"
                full_name = func.concat(Prospect.first_name, " ", Prospect.last_name)
                query = query.where(
                    or_(
                        Prospect.first_name.ilike(term),
                        Prospect.last_name.ilike(term),
                        Prospect.email.ilike(term),
                        full_name.ilike(term),
                    )
                )
        total = self.db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
        rows = (
            self.db.execute(
                query.options(
                    joinedload(Prospect.assigned_to),
                    joinedload(Prospect.merchant),
                )
                .order_by(Prospect.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .unique()
            .scalars()
            .all()
        )
        return list(rows), total

    def get_prospect_detail(self, user: User, prospect_id: int, *, merchant_id: int | None = None) -> Prospect:
        prospect = self._get_prospect_for_user(user, prospect_id, merchant_id=merchant_id)
        return (
            self.db.execute(
                select(Prospect)
                .options(
                    joinedload(Prospect.assigned_to),
                    joinedload(Prospect.merchant),
                    joinedload(Prospect.history).joinedload(ProspectHistory.changed_by),
                    joinedload(Prospect.calendly_event),
                    joinedload(Prospect.docusign_envelope),
                    joinedload(Prospect.payment_link),
                )
                .where(Prospect.id == prospect.id)
            )
            .unique()
            .scalar_one()
        )

    def list_linked_envelopes(self, prospect: Prospect) -> list[DocusignEnvelope]:
        rows = list(
            self.db.execute(
                select(DocusignEnvelope)
                .where(DocusignEnvelope.prospect_id == prospect.id)
                .order_by(DocusignEnvelope.sent_at.desc())
            )
            .scalars()
            .all()
        )
        if prospect.docusign_envelope_id and not any(row.id == prospect.docusign_envelope_id for row in rows):
            linked = prospect.docusign_envelope or self.db.get(DocusignEnvelope, prospect.docusign_envelope_id)
            if linked is not None:
                rows.insert(0, linked)
        return rows

    def create_prospect(
        self,
        *,
        actor: User,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        merchant_id: int,
        is_qualified: bool = True,
        source: str | None = None,
        notes: str | None = None,
        assigned_to_user_id: int | None = None,
    ) -> Prospect:
        if not self.merchant_ctx.user_can_access_merchant(actor, merchant_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenés acceso a ese comercio")

        normalized_email = email.lower().strip()
        self._assert_email_available(normalized_email, merchant_id=merchant_id)
        self._assert_phone_available(phone, merchant_id=merchant_id)

        owner_id = assigned_to_user_id or actor.id
        if actor.role.code == "SALES_REP" and owner_id != actor.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
        owner = self.db.get(User, owner_id)
        if owner is None or owner.role.code != "SALES_REP":
            if actor.role.code == "SALES_REP":
                owner_id = actor.id
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vendedor inválido")

        prospect = Prospect(
            merchant_id=merchant_id,
            assigned_to_user_id=owner_id,
            status=INITIAL_STATUS,
            is_qualified=bool(is_qualified),
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            email=normalized_email,
            phone=phone.strip(),
            source=source,
            notes=notes.strip() if notes else None,
        )
        self.db.add(prospect)
        self.db.flush()
        self._add_history(
            prospect,
            actor=actor,
            event_type=ProspectHistoryEventType.STATUS_CHANGE.value,
            from_status=None,
            to_status=INITIAL_STATUS,
            note="Prospecto creado",
        )
        self.audit.log(
            actor=actor,
            action="PROSPECT_CREATED",
            entity_type="prospect",
            entity_id=prospect.id,
            metadata={"status": INITIAL_STATUS, "is_qualified": prospect.is_qualified},
        )
        self.db.commit()
        self.db.refresh(prospect)
        return prospect

    def update_prospect(
        self,
        *,
        actor: User,
        prospect: Prospect,
        **fields,
    ) -> Prospect:
        if prospect.converted_client_id is not None:
            raise HTTPException(status_code=400, detail="No se puede editar un prospecto ya convertido")
        if "email" in fields and fields["email"] is not None:
            self._assert_email_available(
                fields["email"].lower().strip(),
                merchant_id=prospect.merchant_id,
                exclude_prospect_id=prospect.id,
            )
            fields["email"] = fields["email"].lower().strip()
        if "phone" in fields and fields["phone"] is not None:
            self._assert_phone_available(
                fields["phone"],
                merchant_id=prospect.merchant_id,
                exclude_prospect_id=prospect.id,
            )
        for key, value in fields.items():
            if value is not None and hasattr(prospect, key):
                if isinstance(value, str):
                    setattr(prospect, key, value.strip())
                else:
                    setattr(prospect, key, value)
        self.audit.log(actor=actor, action="PROSPECT_UPDATED", entity_type="prospect", entity_id=prospect.id)
        self.db.commit()
        self.db.refresh(prospect)
        return prospect

    def delete_prospect(self, *, actor: User, prospect: Prospect) -> None:
        """Borrado definitivo, solo para administradores. El historial y los emails
        registrados se eliminan en cascada; links de pago, contratos y reuniones
        vinculados quedan desasociados."""
        if actor.role.code != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo un administrador puede eliminar prospectos",
            )
        self.audit.log(
            actor=actor,
            action="PROSPECT_DELETED",
            entity_type="prospect",
            entity_id=prospect.id,
            metadata={"email": prospect.email},
        )
        self.db.delete(prospect)
        self.db.commit()

    def update_status(
        self,
        *,
        actor: User,
        prospect: Prospect,
        new_status: str,
        note: str | None = None,
    ) -> Prospect:
        if prospect.converted_client_id is not None:
            raise HTTPException(status_code=400, detail="El prospecto ya fue convertido a cliente")
        current = prospect.status
        if new_status == current:
            return prospect
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se puede pasar de {current} a {new_status}",
            )
        if actor.role.code == "SALES_REP" and new_status not in SALES_REP_MANUAL_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El estado se actualiza automáticamente al realizar acciones en el prospecto",
            )
        prospect.status = new_status
        self._add_history(
            prospect,
            actor=actor,
            event_type=ProspectHistoryEventType.STATUS_CHANGE.value,
            from_status=current,
            to_status=new_status,
            note=note,
        )
        self.db.commit()
        self.db.refresh(prospect)
        if new_status == ProspectStatus.PAGO_COMPLETADO.value:
            self.try_auto_convert(prospect.id, actor=actor)
        return prospect

    def mark_contacted(
        self,
        *,
        actor: User,
        prospect: Prospect,
        note: str | None = None,
    ) -> Prospect:
        if prospect.converted_client_id is not None:
            raise HTTPException(status_code=400, detail="El prospecto ya fue convertido a cliente")
        current = prospect.status
        target = ProspectStatus.LEAD_CONTACTADO.value
        if current != ProspectStatus.PENDIENTE_CONTACTAR.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Solo se puede marcar contactado desde pendiente de contactar",
            )
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se puede pasar de {current} a {target}",
            )
        prospect.status = target
        self._add_history(
            prospect,
            actor=actor,
            event_type=ProspectHistoryEventType.STATUS_CHANGE.value,
            from_status=current,
            to_status=target,
            note=note,
        )
        self.db.commit()
        self.db.refresh(prospect)
        self.try_auto_convert(prospect.id, actor=actor)
        return prospect

    def add_note(self, *, actor: User, prospect: Prospect, note: str) -> ProspectHistory:
        entry = self._add_history(
            prospect,
            actor=actor,
            event_type=ProspectHistoryEventType.NOTE.value,
            from_status=prospect.status,
            to_status=prospect.status,
            note=note,
        )
        self.db.commit()
        return entry

    def link_calendly_event(
        self,
        *,
        actor: User,
        prospect: Prospect,
        calendly_event_id: int,
    ) -> Prospect:
        if prospect.converted_client_id is not None:
            raise HTTPException(status_code=400, detail="El prospecto ya fue convertido")
        event = self.db.get(CalendlyEvent, calendly_event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Reunión no encontrada")
        if actor.role.code == "SALES_REP" and event.user_id != actor.id:
            raise HTTPException(status_code=404, detail="Reunión no encontrada")

        previous_event_id = prospect.calendly_event_id
        is_reschedule = previous_event_id is not None and previous_event_id != calendly_event_id

        if previous_event_id and previous_event_id != calendly_event_id:
            previous_event = self.db.get(CalendlyEvent, previous_event_id)
            if previous_event is not None:
                previous_event.prospect_id = None

        if event.prospect_id and event.prospect_id != prospect.id:
            other_prospect = self.db.get(Prospect, event.prospect_id)
            if other_prospect is not None:
                other_prospect.calendly_event_id = None

        prospect.calendly_event_id = event.id
        event.prospect_id = prospect.id

        if is_reschedule:
            reschedule_note = f"Nueva reunión agendada: {event.name}"
            if prospect.status == ProspectStatus.LEAD_CONTACTADO.value:
                self._transition_status(
                    prospect,
                    actor=actor,
                    new_status=ProspectStatus.PENDIENTE_CONTACTAR.value,
                    note=reschedule_note,
                    event_type=ProspectHistoryEventType.CALENDLY_RESCHEDULED.value,
                )
            else:
                self._add_history(
                    prospect,
                    actor=actor,
                    event_type=ProspectHistoryEventType.CALENDLY_RESCHEDULED.value,
                    from_status=prospect.status,
                    to_status=prospect.status,
                    note=reschedule_note,
                )
        else:
            self._add_history(
                prospect,
                actor=actor,
                event_type=ProspectHistoryEventType.CALENDLY_LINKED.value,
                from_status=prospect.status,
                to_status=prospect.status,
                note=f"Reunión vinculada: {event.name}",
            )
        self.db.commit()
        self.db.refresh(prospect)
        return prospect

    def attach_envelope(self, *, actor: User, prospect: Prospect, envelope: DocusignEnvelope) -> Prospect:
        if prospect.converted_client_id is not None:
            return prospect
        prospect.docusign_envelope_id = envelope.id
        envelope.prospect_id = prospect.id
        contract_note = f"Contrato enviado: {envelope.subject}"
        if prospect.status == ProspectStatus.LEAD_CONTACTADO.value:
            self._transition_status(
                prospect,
                actor=actor,
                new_status=ProspectStatus.CONTRATO_ENVIADO.value,
                note=contract_note,
                event_type=ProspectHistoryEventType.CONTRACT_SENT.value,
            )
        else:
            self._add_history(
                prospect,
                actor=actor,
                event_type=ProspectHistoryEventType.CONTRACT_SENT.value,
                from_status=prospect.status,
                to_status=prospect.status,
                note=contract_note,
            )
        self.db.flush()
        return prospect

    def on_envelope_completed(self, envelope: DocusignEnvelope) -> None:
        if envelope.prospect_id is None:
            return
        prospect = self.db.get(Prospect, envelope.prospect_id)
        if prospect is None or prospect.converted_client_id is not None:
            return
        actor = envelope.sent_by
        if actor is None:
            return
        if self._contract_signed_history_exists(prospect.id, envelope.id):
            self.try_auto_convert(prospect.id, actor=actor)
            return
        self._add_history(
            prospect,
            actor=actor,
            event_type=ProspectHistoryEventType.CONTRACT_SIGNED.value,
            from_status=prospect.status,
            to_status=prospect.status,
            note=self._contract_signed_history_note(envelope),
        )
        self.db.flush()
        self.try_auto_convert(prospect.id, actor=actor)

    @staticmethod
    def _contract_signed_history_note(envelope: DocusignEnvelope) -> str:
        return f"Contrato firmado: {envelope.subject} (envelope_id={envelope.id})"

    def _contract_signed_history_exists(self, prospect_id: int, envelope_id: int) -> bool:
        marker = f"envelope_id={envelope_id}"
        existing = self.db.execute(
            select(ProspectHistory.id)
            .where(
                ProspectHistory.prospect_id == prospect_id,
                ProspectHistory.event_type == ProspectHistoryEventType.CONTRACT_SIGNED.value,
                ProspectHistory.note.contains(marker),
            )
            .limit(1)
        ).scalar_one_or_none()
        return existing is not None

    def attach_payment_link(self, *, actor: User, prospect: Prospect, link: PaymentLink) -> Prospect:
        if prospect.converted_client_id is not None:
            return prospect
        prospect.payment_link_id = link.id
        link.prospect_id = prospect.id
        self._add_history(
            prospect,
            actor=actor,
            event_type=ProspectHistoryEventType.PAYMENT_LINKED.value,
            from_status=prospect.status,
            to_status=prospect.status,
            note=f"Link de pago generado ({link.currency} {link.amount})",
        )
        self.db.flush()
        return prospect

    def link_envelope(
        self,
        *,
        actor: User,
        prospect: Prospect,
        envelope_id: int,
    ) -> Prospect:
        if prospect.converted_client_id is not None:
            raise HTTPException(status_code=400, detail="El prospecto ya fue convertido")
        envelope = self.db.get(DocusignEnvelope, envelope_id)
        if envelope is None:
            raise HTTPException(status_code=404, detail="Contrato no encontrado")
        if actor.role.code == "SALES_REP" and envelope.sent_by_user_id != actor.id:
            raise HTTPException(status_code=404, detail="Contrato no encontrado")
        if envelope.signer_email.lower().strip() != prospect.email.lower().strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El email del firmante no coincide con el del prospecto",
            )
        if envelope.prospect_id is not None and envelope.prospect_id != prospect.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El contrato ya está vinculado a otro prospecto",
            )
        prospect = self.attach_envelope(actor=actor, prospect=prospect, envelope=envelope)
        self.db.commit()
        self.db.refresh(prospect)
        return prospect

    def link_payment_link(
        self,
        *,
        actor: User,
        prospect: Prospect,
        payment_link_id: int,
    ) -> Prospect:
        if prospect.converted_client_id is not None:
            raise HTTPException(status_code=400, detail="El prospecto ya fue convertido")
        link = self.db.get(PaymentLink, payment_link_id)
        if link is None:
            raise HTTPException(status_code=404, detail="Link de pago no encontrado")
        if actor.role.code == "SALES_REP" and link.created_by_user_id != actor.id:
            raise HTTPException(status_code=404, detail="Link de pago no encontrado")
        if link.customer_email.lower().strip() != prospect.email.lower().strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El email del link de pago no coincide con el del prospecto",
            )
        if link.prospect_id is not None and link.prospect_id != prospect.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El link de pago ya está vinculado a otro prospecto",
            )
        prospect = self.attach_payment_link(actor=actor, prospect=prospect, link=link)
        self.db.commit()
        self.db.refresh(prospect)
        return prospect

    def on_payment_completed(self, link: PaymentLink) -> None:
        if link.prospect_id is None:
            return
        prospect = self.db.get(Prospect, link.prospect_id)
        if prospect is None or prospect.converted_client_id is not None:
            return
        actor = link.created_by
        if actor is None:
            return
        if prospect.status != ProspectStatus.PAGO_COMPLETADO.value:
            self._transition_status(
                prospect,
                actor=actor,
                new_status=ProspectStatus.PAGO_COMPLETADO.value,
                note="Pago completado",
                event_type=ProspectHistoryEventType.PAYMENT_COMPLETED.value,
            )
        self.db.flush()
        self.try_auto_convert(prospect.id, actor=actor)

    def try_auto_convert(self, prospect_id: int, *, actor: User | None = None) -> Client | None:
        prospect = self.db.get(Prospect, prospect_id)
        if prospect is None or prospect.converted_client_id is not None:
            return None
        if not self._ready_for_conversion(prospect):
            return None
        return self.convert_to_client(prospect=prospect, actor=actor or prospect.assigned_to)

    def convert_to_client(self, *, prospect: Prospect, actor: User) -> Client:
        if prospect.converted_client_id is not None:
            client = self.db.get(Client, prospect.converted_client_id)
            if client is None:
                raise HTTPException(status_code=500, detail="Cliente convertido no encontrado")
            if prospect.payment_link_id is not None:
                link = self.db.get(PaymentLink, prospect.payment_link_id)
                if link is not None:
                    self._send_client_conversion_welcome(client, link)
            return client
        if not self._ready_for_conversion(prospect):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El prospecto debe tener reunión concretada, contrato firmado y pago completado antes de convertirse",
            )

        client_service = ClientService(self.db)
        source = prospect.source or ClientSource.OTHER.value
        client = client_service.create_client(
            actor=actor,
            first_name=prospect.first_name,
            last_name=prospect.last_name,
            email=prospect.email,
            phone=prospect.phone,
            source=source,
            merchant_id=prospect.merchant_id,
            is_qualified=prospect.is_qualified,
        )

        if prospect.docusign_envelope_id:
            envelope = self.db.get(DocusignEnvelope, prospect.docusign_envelope_id)
            if envelope and envelope.status.lower() == "completed":
                client.docusign_envelope_id = envelope.id
                client.docusign_contract_signed_at = envelope.completed_at or datetime.now(timezone.utc)
                envelope.client_id = client.id

        link = (
            self.db.get(PaymentLink, prospect.payment_link_id)
            if prospect.payment_link_id is not None
            else None
        )
        if link and link.status == PaymentLinkStatus.PAID.value:
            link.client_id = client.id
            link.client_registered_at = datetime.now(timezone.utc)

        prospect.converted_client_id = client.id
        prospect.status = ProspectStatus.PAGO_COMPLETADO.value
        self._add_history(
            prospect,
            actor=actor,
            event_type=ProspectHistoryEventType.CONVERTED.value,
            from_status=prospect.status,
            to_status=ProspectStatus.PAGO_COMPLETADO.value,
            note=f"Convertido a cliente #{client.id}",
        )
        self.audit.log(
            actor=actor,
            action="PROSPECT_CONVERTED",
            entity_type="prospect",
            entity_id=prospect.id,
            metadata={"client_id": client.id},
        )
        self.db.commit()
        self.db.refresh(client)
        if link is not None:
            self._send_client_conversion_welcome(client, link)
        return client

    def _send_client_conversion_welcome(self, client: Client, link: PaymentLink) -> None:
        if client.conversion_welcome_email_sent_at is not None:
            return
        merchant = self.db.get(Merchant, client.merchant_id) if client.merchant_id else None
        try:
            sent = send_client_conversion_welcome_email(
                ClientConversionWelcomeEmailPayload(
                    recipient_email=client.email,
                    first_name=client.first_name,
                    amount=link.amount,
                    currency=link.currency,
                    client_id=client.id,
                    merchant_name=merchant.name if merchant else None,
                )
            )
        except Exception:
            logger.exception(
                "Error enviando bienvenida por conversión (client_id=%s)",
                client.id,
            )
            return
        if not sent:
            logger.warning(
                "No se pudo enviar bienvenida por conversión a %s (client_id=%s)",
                client.email,
                client.id,
            )
            return
        client.conversion_welcome_email_sent_at = datetime.now(timezone.utc)
        self.db.commit()

    def _ready_for_conversion(self, prospect: Prospect) -> bool:
        if prospect.status != ProspectStatus.PAGO_COMPLETADO.value:
            return False
        if prospect.calendly_event_id is None:
            return False
        if prospect.status not in MEETING_COMPLETE_STATUSES:
            return False
        if prospect.payment_link_id is None:
            return False
        link = self.db.get(PaymentLink, prospect.payment_link_id)
        if link is None or link.status != PaymentLinkStatus.PAID.value:
            return False
        envelopes = self.list_linked_envelopes(prospect)
        return any(envelope.status.lower() == "completed" for envelope in envelopes)

    def _scoped_query(self, user: User, merchant_id: int | None, *, all_merchants: bool = False):
        query = select(Prospect)
        if all_merchants:
            accessible = self.merchant_ctx.list_accessible_merchants(user)
            merchant_ids = [merchant.id for merchant in accessible]
            if merchant_ids:
                query = query.where(Prospect.merchant_id.in_(merchant_ids))
            else:
                query = query.where(Prospect.id == -1)
        elif merchant_id is not None:
            query = query.where(Prospect.merchant_id == merchant_id)
        if user.role.code == "SALES_REP":
            query = query.where(Prospect.assigned_to_user_id == user.id)
        return query

    def get_pipeline_for_client(
        self,
        user: User,
        client_id: int,
        *,
        merchant_id: int,
    ):
        from app.serializers.prospect_pipeline import load_prospect_pipeline_for_client

        prospect = self.db.execute(
            select(Prospect)
            .options(
                joinedload(Prospect.calendly_event),
                joinedload(Prospect.docusign_envelope),
                joinedload(Prospect.payment_link),
                joinedload(Prospect.history).joinedload(ProspectHistory.changed_by),
            )
            .where(Prospect.converted_client_id == client_id)
            .limit(1)
        ).unique().scalar_one_or_none()
        if prospect is None:
            return None
        try:
            self._get_prospect_for_user(user, prospect.id, merchant_id=merchant_id)
        except HTTPException:
            return None
        return load_prospect_pipeline_for_client(self, prospect)

    def _get_prospect_for_user(
        self,
        user: User,
        prospect_id: int,
        *,
        merchant_id: int | None = None,
    ) -> Prospect:
        prospect = self.db.get(Prospect, prospect_id)
        if prospect is None:
            raise HTTPException(status_code=404, detail="Prospecto no encontrado")
        if merchant_id is not None and prospect.merchant_id != merchant_id:
            if not self.merchant_ctx.user_can_access_merchant(user, prospect.merchant_id):
                raise HTTPException(status_code=404, detail="Prospecto no encontrado")
        elif not self.merchant_ctx.user_can_access_merchant(user, prospect.merchant_id):
            raise HTTPException(status_code=404, detail="Prospecto no encontrado")
        if user.role.code == "SALES_REP" and prospect.assigned_to_user_id != user.id:
            raise HTTPException(status_code=404, detail="Prospecto no encontrado")
        return prospect

    def _assert_email_available(
        self,
        email: str,
        *,
        merchant_id: int,
        exclude_prospect_id: int | None = None,
    ) -> None:
        conflict = self._find_email_conflict(
            email, merchant_id=merchant_id, exclude_prospect_id=exclude_prospect_id
        )
        if conflict is None:
            return
        kind, _ = conflict
        if kind == "client":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe un cliente con ese email en este comercio",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un prospecto activo con ese email en este comercio",
        )

    def _assert_phone_available(
        self,
        phone: str,
        *,
        merchant_id: int,
        exclude_prospect_id: int | None = None,
    ) -> None:
        conflict = self._find_phone_conflict(
            phone, merchant_id=merchant_id, exclude_prospect_id=exclude_prospect_id
        )
        if conflict is None:
            return
        kind, _ = conflict
        if kind == "client":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe un cliente con ese teléfono en este comercio",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un prospecto activo con ese teléfono en este comercio",
        )

    def _find_email_conflict(
        self,
        email: str,
        *,
        merchant_id: int,
        exclude_prospect_id: int | None = None,
    ) -> tuple[str, Client | Prospect] | None:
        normalized = email.lower().strip()
        client = self.db.execute(
            select(Client).where(
                func.lower(Client.email) == normalized,
                Client.merchant_id == merchant_id,
            )
        ).scalar_one_or_none()
        if client is not None:
            return ("client", client)
        prospect_query = select(Prospect).where(
            func.lower(Prospect.email) == normalized,
            Prospect.merchant_id == merchant_id,
            Prospect.converted_client_id.is_(None),
        )
        if exclude_prospect_id is not None:
            prospect_query = prospect_query.where(Prospect.id != exclude_prospect_id)
        prospect = self.db.execute(prospect_query).scalar_one_or_none()
        if prospect is not None:
            return ("prospect", prospect)
        return None

    def _find_phone_conflict(
        self,
        phone: str,
        *,
        merchant_id: int,
        exclude_prospect_id: int | None = None,
    ) -> tuple[str, Client | Prospect] | None:
        from app.core.config import get_settings
        from app.core.phone import phones_match

        normalized = phone.strip()
        if not normalized:
            return None
        country_code = get_settings().whatsapp_default_country_code
        clients = self.db.execute(
            select(Client).where(Client.merchant_id == merchant_id)
        ).scalars()
        for client in clients:
            if phones_match(client.phone, normalized, country_code):
                return ("client", client)
        prospect_query = select(Prospect).where(
            Prospect.merchant_id == merchant_id,
            Prospect.converted_client_id.is_(None),
        )
        if exclude_prospect_id is not None:
            prospect_query = prospect_query.where(Prospect.id != exclude_prospect_id)
        for prospect in self.db.execute(prospect_query).scalars():
            if phones_match(prospect.phone, normalized, country_code):
                return ("prospect", prospect)
        return None

    def check_contact_availability(
        self,
        *,
        email: str | None = None,
        phone: str | None = None,
        merchant_id: int,
        exclude_prospect_id: int | None = None,
    ) -> dict:
        result: dict = {"available": True, "email": None, "phone": None}
        if email and "@" in email:
            conflict = self._find_email_conflict(
                email, merchant_id=merchant_id, exclude_prospect_id=exclude_prospect_id
            )
            if conflict is not None:
                result["available"] = False
                result["email"] = self._conflict_payload(*conflict)
        if phone and len(phone.strip()) >= 5:
            conflict = self._find_phone_conflict(
                phone, merchant_id=merchant_id, exclude_prospect_id=exclude_prospect_id
            )
            if conflict is not None:
                result["available"] = False
                result["phone"] = self._conflict_payload(*conflict)
        return result

    @staticmethod
    def _conflict_payload(kind: str, row: Client | Prospect) -> dict:
        return {
            "client_id": row.id,
            "client_name": row.full_name,
            "client_email": row.email,
            "kind": kind,
        }

    def _transition_status(
        self,
        prospect: Prospect,
        *,
        actor: User,
        new_status: str,
        note: str | None,
        event_type: str,
    ) -> None:
        previous = prospect.status
        if new_status != previous:
            allowed = ALLOWED_TRANSITIONS.get(previous, set())
            if new_status not in allowed:
                return
            prospect.status = new_status
        self._add_history(
            prospect,
            actor=actor,
            event_type=event_type,
            from_status=previous,
            to_status=prospect.status,
            note=note,
        )

    def _add_history(
        self,
        prospect: Prospect,
        *,
        actor: User,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        note: str | None,
    ) -> ProspectHistory:
        entry = ProspectHistory(
            prospect_id=prospect.id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            note=note,
            changed_by_user_id=actor.id,
        )
        self.db.add(entry)
        return entry
