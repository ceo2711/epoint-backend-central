"""Resumen del pipeline comercial de un prospecto (reunión, contrato, pago)."""

from __future__ import annotations

from app.models.prospect import Prospect
from app.schemas.prospect import (
    ProspectCalendlyBrief,
    ProspectEnvelopeBrief,
    ProspectHistoryResponse,
    ProspectPaymentBrief,
    ProspectPipelineSummary,
)
from app.services.prospects import ProspectService


def envelope_brief(env) -> ProspectEnvelopeBrief:
    return ProspectEnvelopeBrief(
        id=env.id,
        subject=env.subject,
        status=env.status,
        signer_name=env.signer_name,
        signer_email=env.signer_email,
        sent_at=env.sent_at,
        completed_at=env.completed_at,
    )


def prospect_pipeline_summary(
    prospect: Prospect,
    *,
    linked_envelopes: list | None = None,
) -> ProspectPipelineSummary:
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
        envelope = envelope_brief(prospect.docusign_envelope)
    envelopes = [envelope_brief(env) for env in (linked_envelopes or [])]
    if not envelopes and envelope is not None:
        envelopes = [envelope]
    payment = None
    if prospect.payment_link:
        link = prospect.payment_link
        payment = ProspectPaymentBrief(
            id=link.id,
            amount=link.amount,
            currency=link.currency,
            status=link.status,
            payment_url=link.payment_url,
            paid_at=link.paid_at,
            created_at=link.created_at,
        )
    return ProspectPipelineSummary(
        prospect_id=prospect.id,
        status=prospect.status,
        is_qualified=bool(prospect.is_qualified),
        history=history,
        calendly_event=calendly,
        docusign_envelopes=envelopes,
        payment_link=payment,
    )


def load_prospect_pipeline_for_client(
    service: ProspectService,
    prospect: Prospect,
) -> ProspectPipelineSummary:
    linked_envelopes = service.list_linked_envelopes(prospect)
    return prospect_pipeline_summary(prospect, linked_envelopes=linked_envelopes)
