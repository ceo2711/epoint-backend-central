import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import ActiveMerchantId, DbSession, require_permissions
from app.models.user import User
from app.models.sent_email import SentEmail
from app.schemas.common import (
    MessageResponse,
    PaginatedResponse,
    SendCustomEmailRequest,
    SentEmailResponse,
)
from app.services.email import CustomMessageEmailPayload, send_custom_message_email
from app.services.email.custom_message import sanitize_message_html
from app.schemas.prospect import (
    ProspectAvailabilityResponse,
    ProspectCalendlyBrief,
    ProspectConvertResponse,
    ProspectCreate,
    ProspectDetailResponse,
    ProspectEnvelopeBrief,
    ProspectHistoryNote,
    ProspectHistoryResponse,
    ProspectLinkCalendlyEvent,
    ProspectLinkEnvelope,
    ProspectLinkPaymentLink,
    ProspectMarkContacted,
    ProspectPaymentBrief,
    ProspectResponse,
    ProspectStatusUpdate,
    ProspectUpdate,
    SalesRepBrief,
)
from app.services.merchant_context import MerchantContextService
from app.services.prospects import ProspectService

router = APIRouter(prefix="/prospects", tags=["Prospectos"])


def _to_response(prospect) -> ProspectResponse:
    assigned = None
    if prospect.assigned_to:
        assigned = SalesRepBrief(
            id=prospect.assigned_to.id,
            first_name=prospect.assigned_to.first_name,
            last_name=prospect.assigned_to.last_name,
            email=prospect.assigned_to.email,
        )
    return ProspectResponse(
        id=prospect.id,
        merchant_id=prospect.merchant_id,
        assigned_to_user_id=prospect.assigned_to_user_id,
        status=prospect.status,
        is_qualified=bool(prospect.is_qualified),
        first_name=prospect.first_name,
        last_name=prospect.last_name,
        full_name=prospect.full_name,
        email=prospect.email,
        phone=prospect.phone,
        source=prospect.source,
        influencer_id=prospect.influencer_id,
        influencer_name=prospect.influencer.name if getattr(prospect, "influencer", None) else None,
        notes=prospect.notes,
        converted_client_id=prospect.converted_client_id,
        calendly_event_id=prospect.calendly_event_id,
        docusign_envelope_id=prospect.docusign_envelope_id,
        payment_link_id=prospect.payment_link_id,
        created_at=prospect.created_at,
        updated_at=prospect.updated_at,
        assigned_to=assigned,
        merchant_name=prospect.merchant.name if prospect.merchant else None,
    )


def _envelope_brief(env) -> ProspectEnvelopeBrief:
    return ProspectEnvelopeBrief(
        id=env.id,
        subject=env.subject,
        status=env.status,
        signer_name=env.signer_name,
        signer_email=env.signer_email,
        sent_at=env.sent_at,
        completed_at=env.completed_at,
    )


def _payment_brief(link) -> ProspectPaymentBrief:
    return ProspectPaymentBrief(
        id=link.id,
        amount=link.amount,
        currency=link.currency,
        status=link.status,
        payment_url=link.payment_url,
        paid_at=link.paid_at,
        created_at=link.created_at,
    )


def _to_detail(
    prospect,
    *,
    linked_envelopes: list | None = None,
    linked_payment_links: list | None = None,
) -> ProspectDetailResponse:
    base = _to_response(prospect).model_dump()
    history = [
        ProspectHistoryResponse(
            id=entry.id,
            event_type=entry.event_type,
            from_status=entry.from_status,
            to_status=entry.to_status,
            note=entry.note,
            changed_by_user_id=entry.changed_by_user_id,
            created_at=entry.created_at,
            changed_by_name=(
                f"{entry.changed_by.first_name} {entry.changed_by.last_name}".strip()
                if entry.changed_by
                else None
            ),
        )
        for entry in prospect.history
    ]
    calendly = None
    if prospect.calendly_event:
        event = prospect.calendly_event
        calendly = ProspectCalendlyBrief(
            id=event.id,
            name=event.name,
            status=event.status,
            start_time=event.start_time,
            end_time=event.end_time,
            invitee_name=event.invitee_name,
            invitee_email=event.invitee_email,
            meeting_url=event.meeting_url,
            event_type_name=event.event_type_name,
        )
    envelope = None
    if prospect.docusign_envelope:
        envelope = _envelope_brief(prospect.docusign_envelope)
    envelopes = [_envelope_brief(env) for env in (linked_envelopes or [])]
    if not envelopes and envelope is not None:
        envelopes = [envelope]
    payments = [_payment_brief(link) for link in (linked_payment_links or [])]
    payment = None
    if prospect.payment_link:
        payment = _payment_brief(prospect.payment_link)
    elif payments:
        payment = payments[0]
    if payment and not any(item.id == payment.id for item in payments):
        payments = [payment, *payments]
    return ProspectDetailResponse(
        **base,
        history=history,
        calendly_event=calendly,
        docusign_envelope=envelope,
        docusign_envelopes=envelopes,
        payment_link=payment,
        payment_links=payments,
    )


@router.get("", response_model=PaginatedResponse[ProspectResponse])
def list_prospects(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:read"))],
    active_merchant_id: ActiveMerchantId,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = None,
    search: str | None = None,
    sales_rep_id: int | None = Query(None, description="Filtrar por vendedor (admin)"),
    sede_id: int | None = Query(None, description="Filtrar por sede (admin global)"),
    all_merchants: bool = Query(False),
    include_converted: bool = Query(False),
) -> PaginatedResponse[ProspectResponse]:
    service = ProspectService(db)
    merchant_context = MerchantContextService(db)
    if all_merchants:
        scope_merchant_id = None
        scope_all = True
    else:
        scope_merchant_id = active_merchant_id
        scope_all = False

    rows, total = service.list_prospects(
        current_user,
        merchant_id=scope_merchant_id,
        all_merchants=scope_all,
        filter_sede_id=sede_id,
        sales_rep_id=sales_rep_id,
        status_filter=status_filter,
        search=search,
        include_converted=include_converted,
        page=page,
        page_size=page_size,
    )
    return PaginatedResponse(
        items=[_to_response(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)) if total else 1,
    )


@router.post("", response_model=ProspectResponse, status_code=status.HTTP_201_CREATED)
def create_prospect(
    payload: ProspectCreate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:create"))],
) -> ProspectResponse:
    from app.services.sources import require_active_source_code

    try:
        source = require_active_source_code(db, payload.source)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    service = ProspectService(db)
    prospect = service.create_prospect(
        actor=current_user,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=str(payload.email),
        phone=payload.phone,
        merchant_id=payload.merchant_id,
        is_qualified=payload.is_qualified,
        source=source,
        notes=payload.notes,
        assigned_to_user_id=payload.assigned_to_user_id,
        sede_id=payload.sede_id,
        influencer_id=payload.influencer_id,
    )
    detail = service.get_prospect_detail(current_user, prospect.id)
    return _to_response(detail)


@router.get("/check-availability", response_model=ProspectAvailabilityResponse)
def check_prospect_availability(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:create"))],
    merchant_id: int = Query(..., ge=1),
    email: str | None = Query(default=None),
    phone: str | None = Query(default=None),
    exclude_prospect_id: int | None = Query(default=None),
) -> ProspectAvailabilityResponse:
    service = ProspectService(db)
    if not MerchantContextService(db).user_can_access_merchant(current_user, merchant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a ese comercio")
    result = service.check_contact_availability(
        email=email,
        phone=phone,
        merchant_id=merchant_id,
        exclude_prospect_id=exclude_prospect_id,
    )
    return ProspectAvailabilityResponse(**result)


@router.delete("/{prospect_id}", response_model=MessageResponse)
def delete_prospect(
    prospect_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:update"))],
    active_merchant_id: ActiveMerchantId,
) -> MessageResponse:
    """Borrado definitivo del prospecto (solo administradores)."""
    service = ProspectService(db)
    prospect = service._get_prospect_for_user(current_user, prospect_id, merchant_id=active_merchant_id)
    service.delete_prospect(actor=current_user, prospect=prospect)
    return MessageResponse(message="Prospecto eliminado definitivamente")


@router.get("/{prospect_id}", response_model=ProspectDetailResponse)
def get_prospect(
    prospect_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:read"))],
    active_merchant_id: ActiveMerchantId,
) -> ProspectDetailResponse:
    service = ProspectService(db)
    prospect = service.get_prospect_detail(current_user, prospect_id, merchant_id=active_merchant_id)
    linked_envelopes = service.list_linked_envelopes(prospect)
    linked_payment_links = service.list_linked_payment_links(prospect)
    return _to_detail(
        prospect,
        linked_envelopes=linked_envelopes,
        linked_payment_links=linked_payment_links,
    )


@router.patch("/{prospect_id}", response_model=ProspectResponse)
def update_prospect(
    prospect_id: int,
    payload: ProspectUpdate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:update"))],
    active_merchant_id: ActiveMerchantId,
) -> ProspectResponse:
    service = ProspectService(db)
    prospect = service._get_prospect_for_user(current_user, prospect_id, merchant_id=active_merchant_id)
    fields = payload.model_dump(exclude_unset=True)
    if "source" in fields:
        from app.services.sources import require_active_source_code

        try:
            fields["source"] = require_active_source_code(db, fields["source"])
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if "source" in fields or "influencer_id" in fields:
        from app.services.influencers import resolve_prospect_influencer_id

        next_source = fields["source"] if "source" in fields else prospect.source
        next_influencer_id = (
            fields["influencer_id"] if "influencer_id" in fields else prospect.influencer_id
        )
        try:
            fields["influencer_id"] = resolve_prospect_influencer_id(
                db,
                source=next_source,
                influencer_id=next_influencer_id,
                sede_id=prospect.sede_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    prospect = service.update_prospect(actor=current_user, prospect=prospect, **fields)
    detail = service.get_prospect_detail(current_user, prospect.id, merchant_id=active_merchant_id)
    return _to_response(detail)


@router.post("/{prospect_id}/status", response_model=ProspectResponse)
def update_prospect_status(
    prospect_id: int,
    payload: ProspectStatusUpdate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:update"))],
    active_merchant_id: ActiveMerchantId,
) -> ProspectResponse:
    service = ProspectService(db)
    prospect = service._get_prospect_for_user(current_user, prospect_id, merchant_id=active_merchant_id)
    prospect = service.update_status(
        actor=current_user,
        prospect=prospect,
        new_status=payload.status.value,
        note=payload.note,
    )
    detail = service.get_prospect_detail(current_user, prospect.id, merchant_id=active_merchant_id)
    return _to_response(detail)


@router.post("/{prospect_id}/mark-contacted", response_model=ProspectResponse)
def mark_prospect_contacted(
    prospect_id: int,
    payload: ProspectMarkContacted,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:update"))],
    active_merchant_id: ActiveMerchantId,
) -> ProspectResponse:
    service = ProspectService(db)
    prospect = service._get_prospect_for_user(current_user, prospect_id, merchant_id=active_merchant_id)
    prospect = service.mark_contacted(actor=current_user, prospect=prospect, note=payload.note)
    detail = service.get_prospect_detail(current_user, prospect.id, merchant_id=active_merchant_id)
    return _to_response(detail)


@router.post("/{prospect_id}/notes", response_model=ProspectHistoryResponse)
def add_prospect_note(
    prospect_id: int,
    payload: ProspectHistoryNote,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:update"))],
    active_merchant_id: ActiveMerchantId,
) -> ProspectHistoryResponse:
    service = ProspectService(db)
    prospect = service._get_prospect_for_user(current_user, prospect_id, merchant_id=active_merchant_id)
    entry = service.add_note(actor=current_user, prospect=prospect, note=payload.note)
    return ProspectHistoryResponse(
        id=entry.id,
        event_type=entry.event_type,
        from_status=entry.from_status,
        to_status=entry.to_status,
        note=entry.note,
        changed_by_user_id=entry.changed_by_user_id,
        created_at=entry.created_at,
        changed_by_name=f"{current_user.first_name} {current_user.last_name}".strip(),
    )


@router.post("/{prospect_id}/send-email", response_model=MessageResponse)
def send_prospect_email(
    prospect_id: int,
    payload: SendCustomEmailRequest,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:update"))],
    active_merchant_id: ActiveMerchantId,
) -> MessageResponse:
    service = ProspectService(db)
    prospect = service._get_prospect_for_user(current_user, prospect_id, merchant_id=active_merchant_id)
    subject = payload.subject.strip()
    if not subject:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El asunto es obligatorio")
    sender_name = f"{current_user.first_name} {current_user.last_name}".strip()
    sent = send_custom_message_email(
        CustomMessageEmailPayload(
            recipient_email=prospect.email,
            first_name=prospect.first_name,
            subject=subject,
            message_html=payload.message_html,
            sender_name=sender_name,
            log_context=f"prospect email id={prospect.id}",
        )
    )
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo enviar el email. Revisá el mensaje e intentá de nuevo.",
        )
    db.add(
        SentEmail(
            prospect_id=prospect.id,
            recipient_email=prospect.email,
            subject=subject,
            message_html=sanitize_message_html(payload.message_html),
            sent_by_user_id=current_user.id,
        )
    )
    service.add_note(
        actor=current_user,
        prospect=prospect,
        note=f"Email enviado: {subject}",
    )
    return MessageResponse(message=f"Email enviado a {prospect.email}")


@router.get("/{prospect_id}/emails", response_model=list[SentEmailResponse])
def list_prospect_emails(
    prospect_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:read"))],
    active_merchant_id: ActiveMerchantId,
) -> list[SentEmailResponse]:
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    service = ProspectService(db)
    prospect = service._get_prospect_for_user(current_user, prospect_id, merchant_id=active_merchant_id)
    rows = (
        db.execute(
            select(SentEmail)
            .options(joinedload(SentEmail.sent_by))
            .where(SentEmail.prospect_id == prospect.id)
            .order_by(SentEmail.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        SentEmailResponse(
            id=row.id,
            subject=row.subject,
            message_html=row.message_html,
            recipient_email=row.recipient_email,
            sent_by_name=f"{row.sent_by.first_name} {row.sent_by.last_name}".strip(),
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/{prospect_id}/link-calendly", response_model=ProspectResponse)
def link_calendly_event(
    prospect_id: int,
    payload: ProspectLinkCalendlyEvent,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:update"))],
    active_merchant_id: ActiveMerchantId,
) -> ProspectResponse:
    service = ProspectService(db)
    prospect = service._get_prospect_for_user(current_user, prospect_id, merchant_id=active_merchant_id)
    prospect = service.link_calendly_event(
        actor=current_user,
        prospect=prospect,
        calendly_event_id=payload.calendly_event_id,
    )
    detail = service.get_prospect_detail(current_user, prospect.id, merchant_id=active_merchant_id)
    return _to_response(detail)


@router.post("/{prospect_id}/link-envelope", response_model=ProspectResponse)
def link_envelope(
    prospect_id: int,
    payload: ProspectLinkEnvelope,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:update"))],
    active_merchant_id: ActiveMerchantId,
) -> ProspectResponse:
    service = ProspectService(db)
    prospect = service._get_prospect_for_user(current_user, prospect_id, merchant_id=active_merchant_id)
    prospect = service.link_envelope(
        actor=current_user,
        prospect=prospect,
        envelope_id=payload.envelope_id,
    )
    detail = service.get_prospect_detail(current_user, prospect.id, merchant_id=active_merchant_id)
    return _to_response(detail)


@router.post("/{prospect_id}/link-payment", response_model=ProspectResponse)
def link_payment_link(
    prospect_id: int,
    payload: ProspectLinkPaymentLink,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:update"))],
    active_merchant_id: ActiveMerchantId,
) -> ProspectResponse:
    service = ProspectService(db)
    prospect = service._get_prospect_for_user(current_user, prospect_id, merchant_id=active_merchant_id)
    prospect = service.link_payment_link(
        actor=current_user,
        prospect=prospect,
        payment_link_id=payload.payment_link_id,
    )
    detail = service.get_prospect_detail(current_user, prospect.id, merchant_id=active_merchant_id)
    return _to_response(detail)


@router.post("/{prospect_id}/convert", response_model=ProspectConvertResponse)
def convert_prospect(
    prospect_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("prospects:update"))],
    active_merchant_id: ActiveMerchantId,
) -> ProspectConvertResponse:
    service = ProspectService(db)
    prospect = service._get_prospect_for_user(current_user, prospect_id, merchant_id=active_merchant_id)
    client = service.convert_to_client(prospect=prospect, actor=current_user)
    return ProspectConvertResponse(
        prospect_id=prospect.id,
        client_id=client.id,
        message="Prospecto convertido a cliente pendiente de revisión",
    )
