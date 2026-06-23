from app.models.client import Client
from app.schemas.client import ClientResponse, MerchantBrief


def client_to_response(client: Client) -> ClientResponse:
    merchant = None
    if client.merchant:
        merchant = MerchantBrief.model_validate(client.merchant)
    return ClientResponse(
        id=client.id,
        status=client.status,
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
    )
