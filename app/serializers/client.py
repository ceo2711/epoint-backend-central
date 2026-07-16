from app.models.client import Client
from app.schemas.client import ClientResponse, ClientSignedContractBrief, MerchantBrief


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


def client_to_response(client: Client) -> ClientResponse:
    merchant = None
    if client.merchant:
        merchant = MerchantBrief.model_validate(client.merchant)
    return ClientResponse(
        id=client.id,
        status=client.status,
        is_qualified=bool(getattr(client, "is_qualified", True)),
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
        created_at=client.created_at,
        docusign_contract_signed_at=client.docusign_contract_signed_at,
        signed_contract=client_signed_contract_brief(client),
    )
