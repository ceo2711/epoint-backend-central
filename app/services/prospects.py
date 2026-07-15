from __future__ import annotations

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
from app.services.merchant_context import MerchantContextService

INITIAL_STATUSES = {
    ProspectStatus.LEAD_CALIFICADO.value,
    ProspectStatus.LEAD_NO_CALIFICADO.value,
}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ProspectStatus.LEAD_CALIFICADO.value: {
        ProspectStatus.PENDIENTE_CONTACTAR.value,
        ProspectStatus.LEAD_CONTACTADO.value,
        ProspectStatus.LEAD_CERRADO.value,
    },
    ProspectStatus.LEAD_NO_CALIFICADO.value: {
        ProspectStatus.LEAD_CERRADO.value,
    },
    ProspectStatus.PENDIENTE_CONTACTAR.value: {
        ProspectStatus.LEAD_CONTACTADO.value,
        ProspectStatus.LEAD_CERRADO.value,
    },
    ProspectStatus.LEAD_CONTACTADO.value: {
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
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Prospect.first_name.ilike(term),
                    Prospect.last_name.ilike(term),
                    Prospect.email.ilike(term),
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

    def create_prospect(
        self,
        *,
        actor: User,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        merchant_id: int,
        initial_status: str,
        source: str | None = None,
        notes: str | None = None,
        assigned_to_user_id: int | None = None,
    ) -> Prospect:
        if initial_status not in INITIAL_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El estado inicial debe ser LEAD_CALIFICADO o LEAD_NO_CALIFICADO",
            )
        if not self.merchant_ctx.user_can_access_merchant(actor, merchant_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenés acceso a ese comercio")

        normalized_email = email.lower().strip()
        self._assert_email_available(normalized_email, merchant_id=merchant_id)

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
            status=initial_status,
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
            to_status=initial_status,
            note="Prospecto creado",
        )
        self.audit.log(
            actor=actor,
            action="PROSPECT_CREATED",
            entity_type="prospect",
            entity_id=prospect.id,
            metadata={"status": initial_status},
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
        prospect.calendly_event_id = event.id
        event.prospect_id = prospect.id
        if prospect.status == ProspectStatus.LEAD_CALIFICADO.value:
            self._transition_status(
                prospect,
                actor=actor,
                new_status=ProspectStatus.PENDIENTE_CONTACTAR.value,
                note=f"Reunión agendada: {event.name}",
                event_type=ProspectHistoryEventType.CALENDLY_LINKED.value,
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
        if prospect.status == ProspectStatus.LEAD_CONTACTADO.value:
            self._transition_status(
                prospect,
                actor=actor,
                new_status=ProspectStatus.CONTRATO_ENVIADO.value,
                note="Contrato enviado",
                event_type=ProspectHistoryEventType.CONTRACT_SENT.value,
            )
        else:
            self._add_history(
                prospect,
                actor=actor,
                event_type=ProspectHistoryEventType.CONTRACT_SENT.value,
                from_status=prospect.status,
                to_status=prospect.status,
                note="Contrato enviado",
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
        self._add_history(
            prospect,
            actor=actor,
            event_type=ProspectHistoryEventType.CONTRACT_SIGNED.value,
            from_status=prospect.status,
            to_status=prospect.status,
            note="Contrato firmado",
        )
        self.db.flush()
        self.try_auto_convert(prospect.id, actor=actor)

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
            return client
        if not self._ready_for_conversion(prospect):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El prospecto debe tener contrato firmado y pago completado antes de convertirse",
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
        )

        if prospect.docusign_envelope_id:
            envelope = self.db.get(DocusignEnvelope, prospect.docusign_envelope_id)
            if envelope and envelope.status.lower() == "completed":
                client.docusign_envelope_id = envelope.id
                client.docusign_contract_signed_at = envelope.completed_at or datetime.now(timezone.utc)
                envelope.client_id = client.id

        if prospect.payment_link_id:
            link = self.db.get(PaymentLink, prospect.payment_link_id)
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
        return client

    def _ready_for_conversion(self, prospect: Prospect) -> bool:
        if prospect.status != ProspectStatus.PAGO_COMPLETADO.value:
            return False
        if prospect.docusign_envelope_id is None or prospect.payment_link_id is None:
            return False
        envelope = self.db.get(DocusignEnvelope, prospect.docusign_envelope_id)
        link = self.db.get(PaymentLink, prospect.payment_link_id)
        if envelope is None or link is None:
            return False
        return envelope.status.lower() == "completed" and link.status == PaymentLinkStatus.PAID.value

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
        client_query = select(Client.id).where(
            func.lower(Client.email) == email,
            Client.merchant_id == merchant_id,
        )
        if self.db.execute(client_query).scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe un cliente con ese email en este comercio",
            )
        prospect_query = select(Prospect.id).where(
            func.lower(Prospect.email) == email,
            Prospect.merchant_id == merchant_id,
            Prospect.converted_client_id.is_(None),
        )
        if exclude_prospect_id is not None:
            prospect_query = prospect_query.where(Prospect.id != exclude_prospect_id)
        if self.db.execute(prospect_query).scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe un prospecto activo con ese email en este comercio",
            )

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
            if new_status not in allowed and previous not in INITIAL_STATUSES:
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
