from app.models.client import Client
from app.schemas.client import AdvisorBrief, ClientResponse, ClientSignedContractBrief, MerchantBrief
from app.services.client_onboarding_status import is_board_unlocked
from app.services.document_requirements import all_required_documents_approved


def client_signed_contract_brief(client: Client) -> ClientSignedContractBrief | None:
    if not client.docusign_contract_signed_at or not client.docusign_envelope_id:
        return None
    envelope = getattr(client, "docusign_envelope", None)
    subject = envelope.subject if envelope is not None else "Contrato firmado"
    has_document = bool(
        envelope
        and (
            envelope.signed_storage_key
            or envelope.status.lower() == "completed"
        )
    )
    return ClientSignedContractBrief(
        envelope_id=client.docusign_envelope_id,
        signed_at=client.docusign_contract_signed_at,
        subject=subject,
        has_document=has_document,
    )


def client_to_response(
    client: Client,
    *,
    has_unread_inbound_email: bool = False,
    source_prospect_status: str | None = None,
) -> ClientResponse:
    merchant = None
    if client.merchant:
        merchant = MerchantBrief.model_validate(client.merchant)
    registered_by = None
    seller = getattr(client, "registered_by", None)
    if seller is not None:
        registered_by = AdvisorBrief(
            id=seller.id,
            first_name=seller.first_name,
            last_name=seller.last_name,
            email=seller.email,
        )
    advisors: list[AdvisorBrief] = []
    for assignment in getattr(client, "assignments", []) or []:
        if assignment.unassigned_at is None and assignment.advisor is not None:
            advisor_user = assignment.advisor
            advisors.append(
                AdvisorBrief(
                    id=advisor_user.id,
                    first_name=advisor_user.first_name,
                    last_name=advisor_user.last_name,
                    email=advisor_user.email,
                )
            )
    advisor = advisors[0] if advisors else None
    return ClientResponse(
        id=client.id,
        status=client.status,
        is_qualified=getattr(client, "is_qualified", None),
        first_name=client.first_name,
        last_name=client.last_name,
        email=client.email,
        phone=client.phone,
        source=client.source,
        merchant=merchant,
        rejection_reason=client.rejection_reason,
        rejected_at=client.rejected_at,
        approved_at=client.approved_at,
        date_of_birth=client.date_of_birth,
        has_ssn=bool(client.ssn_encrypted),
        registered_by_user_id=client.registered_by_user_id,
        registered_by=registered_by,
        advisor=advisor,
        advisors=advisors,
        created_at=client.created_at,
        docusign_contract_signed_at=client.docusign_contract_signed_at,
        signed_contract=client_signed_contract_brief(client),
        board_unlocked=_compute_board_unlocked(client),
        has_unread_inbound_email=has_unread_inbound_email,
        source_prospect_status=source_prospect_status,
    )


def _compute_board_unlocked(client: Client) -> bool:
    if not is_board_unlocked(client.status):
        return False
    docs = getattr(client, "documents", None)
    if docs is None:
        return True
    return all_required_documents_approved(list(docs))
