import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select

from app.api.deps import ActiveMerchantId, DbSession, get_user_permissions, require_permissions
from app.models.client import Client
from app.models.user import User
from app.schemas.client import (
    ClientApprove,
    ClientApproveResponse,
    ClientAssignAdvisor,
    ClientAvailabilityResponse,
    ClientBulkDeleteRequest,
    ClientBulkDeleteResponse,
    ClientCreate,
    ClientDetailResponse,
    ClientPortalPasswordResponse,
    ClientReject,
    ClientResponse,
    ClientStatsResponse,
    ClientUpdate,
    AdvisorBrief,
)
from app.models.sent_email import SentEmail
from app.schemas.common import (
    InboxSyncResponse,
    MessageResponse,
    PaginatedResponse,
    SendCustomEmailRequest,
    SentEmailResponse,
)
from app.services.email import CustomMessageEmailPayload, send_custom_message_email
from app.services.email.custom_message import sanitize_message_html
from app.serializers.client import client_to_response
from app.services.client_email_inbox import (
    list_client_thread,
    mark_client_inbound_read,
    unread_inbound_client_ids,
)
from app.services.email.resend_inbound import sync_receiving_inbox
from app.services.clients import ClientService
from app.services.merchant_context import MerchantContextService
from app.services.prospects import ProspectService
from app.services.documents import DocumentService
from app.services.docusign.service import DocusignService

router = APIRouter(prefix="/clients", tags=["Clientes"])


def _to_response(client: Client) -> ClientResponse:
    return client_to_response(client)


@router.get("", response_model=PaginatedResponse[ClientResponse])
def list_clients(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
    active_merchant_id: ActiveMerchantId,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = None,
    search: str | None = None,
    onboarding_only: bool = Query(False),
    merchant_id: int | None = Query(None, description="Filtrar por comercio específico"),
    all_merchants: bool = Query(False, description="Incluir todos los comercios accesibles"),
    sales_rep_id: int | None = Query(None, description="Filtrar por vendedor o subvendedor"),
    sede_id: int | None = Query(None, description="Filtrar por sede (admin global)"),
) -> PaginatedResponse[ClientResponse]:
    service = ClientService(db)
    merchant_context = MerchantContextService(db)

    if merchant_id is not None:
        if not merchant_context.user_can_access_merchant(current_user, merchant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes acceso a ese comercio",
            )
        scope_merchant_id = merchant_id
        scope_all_merchants = False
    elif all_merchants:
        scope_merchant_id = None
        scope_all_merchants = True
    else:
        scope_merchant_id = active_merchant_id
        scope_all_merchants = False

    clients, total = service.list_clients_for_user(
        current_user,
        merchant_id=scope_merchant_id,
        all_merchants=scope_all_merchants,
        filter_sede_id=sede_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        search=search,
        onboarding_only=onboarding_only,
        sales_rep_id=sales_rep_id,
    )
    sync_receiving_inbox(db)
    unread_ids = unread_inbound_client_ids(db, [c.id for c in clients])
    return PaginatedResponse(
        items=[
            client_to_response(c, has_unread_inbound_email=c.id in unread_ids)
            for c in clients
        ],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


@router.get("/check-availability", response_model=ClientAvailabilityResponse)
def check_client_availability(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:create"))],
    merchant_id: ActiveMerchantId,
    email: str | None = Query(default=None),
    phone: str | None = Query(default=None),
    exclude_client_id: int | None = Query(default=None),
) -> ClientAvailabilityResponse:
    service = ClientService(db)
    result = service.check_contact_availability(
        email=email,
        phone=phone,
        merchant_id=merchant_id,
        exclude_client_id=exclude_client_id,
    )
    return ClientAvailabilityResponse(**result)


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientCreate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:create"))],
    merchant_id: ActiveMerchantId,
) -> ClientResponse:
    from app.services.sources import require_active_source_code

    try:
        source = require_active_source_code(db, payload.source, required=True)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    service = ClientService(db)
    client = service.create_client(
        actor=current_user,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=str(payload.email),
        phone=payload.phone,
        source=source,
        merchant_id=payload.merchant_id or merchant_id,
    )[0]
    db.refresh(client, attribute_names=["merchant"])
    return _to_response(client)


@router.get("/stats", response_model=ClientStatsResponse)
def get_client_stats(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
    merchant_id: ActiveMerchantId,
) -> ClientStatsResponse:
    service = ClientService(db)
    return ClientStatsResponse(**service.get_client_stats(current_user, merchant_id=merchant_id))


@router.post("/inbox/sync", response_model=InboxSyncResponse)
def sync_client_inbox(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
) -> InboxSyncResponse:
    ingested = sync_receiving_inbox(db)
    return InboxSyncResponse(ingested=ingested)


@router.post("/bulk-delete", response_model=ClientBulkDeleteResponse)
def bulk_delete_clients(
    payload: ClientBulkDeleteRequest,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:delete"))],
) -> ClientBulkDeleteResponse:
    service = ClientService(db)
    result = service.bulk_delete_clients(actor=current_user, client_ids=payload.client_ids)
    return ClientBulkDeleteResponse(**result)


@router.get("/{client_id}/signed-contract")
def download_client_signed_contract(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
    merchant_id: ActiveMerchantId,
) -> StreamingResponse:
    """Descarga el contrato DocuSign firmado vinculado al cliente (onboarding / ventas)."""
    service = ClientService(db)
    if not service.user_can_view_approved_client_workspace(current_user, client_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
    if not service.user_can_access_client(current_user, client_id, merchant_id=merchant_id):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    content, filename = DocusignService(db).get_client_signed_contract(current_user, client_id)
    return StreamingResponse(
        iter([content]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/{client_id}", response_model=ClientDetailResponse)
def get_client(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
    merchant_id: ActiveMerchantId,
) -> ClientDetailResponse:
    service = ClientService(db)
    if not service.user_can_access_client(current_user, client_id, merchant_id=merchant_id):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client = service.get_client_detail(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    base = _to_response(client)
    portal = service.get_portal_access_info(client)
    portal_temp_password = service.get_stored_portal_temp_password(client)
    doc_service = DocumentService(db)
    latest_verifications = doc_service.load_latest_verifications_map([doc.id for doc in client.documents])
    can_view_onboarding = service.user_can_view_approved_client_workspace(
        current_user, client_id, client=client
    )
    response = ClientDetailResponse(
        **base.model_dump(),
        **portal,
        portal_temp_password=portal_temp_password,
        addresses=client.addresses if can_view_onboarding else [],
        vehicles=client.vehicles if can_view_onboarding else [],
        documents=[
            doc_service.to_brief(
                doc,
                include_download_url=False,
                latest_verification=latest_verifications.get(doc.id),
            )
            for doc in client.documents
        ]
        if can_view_onboarding
        else [],
    )
    user_perms = set(get_user_permissions(db, current_user))
    if current_user.role.code == "ADMIN" or current_user.role.code == "BRANCH_MANAGER" or "prospects:read" in user_perms:
        response.source_prospect = ProspectService(db).get_pipeline_for_client(
            current_user,
            client_id,
            merchant_id=merchant_id,
        )
    if not can_view_onboarding:
        response.date_of_birth = None
        response.has_ssn = False
        response.signed_contract = None
        response.docusign_contract_signed_at = None
        response.has_portal_access = False
        response.portal_email = None
        response.portal_login_url = None
        response.portal_temp_password = None
        # El asesor asignado sigue visible para ventas (contacto operativo).
    return response


@router.patch("/{client_id}", response_model=ClientResponse)
def update_client(
    client_id: int,
    payload: ClientUpdate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:update"))],
    merchant_id: ActiveMerchantId,
) -> ClientResponse:
    service = ClientService(db)
    client = service.get_client_for_user(current_user, client_id, merchant_id=merchant_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    fields = payload.model_dump(exclude_unset=True)
    if "source" in fields:
        from app.services.sources import require_active_source_code

        try:
            fields["source"] = require_active_source_code(db, fields["source"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    client = service.update_client(actor=current_user, client=client, **fields)
    db.refresh(client, attribute_names=["merchant"])
    return _to_response(client)


@router.post("/{client_id}/send-email", response_model=MessageResponse)
def send_client_email(
    client_id: int,
    payload: SendCustomEmailRequest,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
    merchant_id: ActiveMerchantId,
) -> MessageResponse:
    service = ClientService(db)
    client = service.get_client_for_user(current_user, client_id, merchant_id=merchant_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    subject = payload.subject.strip()
    if not subject:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El asunto es obligatorio")
    sender_name = f"{current_user.first_name} {current_user.last_name}".strip()
    sent = send_custom_message_email(
        CustomMessageEmailPayload(
            recipient_email=client.email,
            first_name=client.first_name,
            subject=subject,
            message_html=payload.message_html,
            sender_name=sender_name,
            log_context=f"client email id={client.id}",
        )
    )
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo enviar el email. Revisá el mensaje e intentá de nuevo.",
        )
    db.add(
        SentEmail(
            client_id=client.id,
            recipient_email=client.email,
            subject=subject,
            message_html=sanitize_message_html(payload.message_html),
            sent_by_user_id=current_user.id,
        )
    )
    service.audit.log(
        actor=current_user,
        action="CLIENT_EMAIL_SENT",
        entity_type="client",
        entity_id=client.id,
        metadata={"subject": subject},
    )
    db.commit()
    return MessageResponse(message=f"Email enviado a {client.email}")


@router.get("/{client_id}/emails", response_model=PaginatedResponse[SentEmailResponse])
def list_client_emails(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
    merchant_id: ActiveMerchantId,
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=1, le=50),
) -> PaginatedResponse[SentEmailResponse]:
    service = ClientService(db)
    client = service.get_client_for_user(current_user, client_id, merchant_id=merchant_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    sync_receiving_inbox(db, force=True)
    items, total = list_client_thread(db, client, page=page, page_size=page_size)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)) if total else 1,
    )


@router.post("/{client_id}/emails/mark-read", response_model=MessageResponse)
def mark_client_emails_read(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
    merchant_id: ActiveMerchantId,
    email_id: int | None = Query(None),
) -> MessageResponse:
    service = ClientService(db)
    client = service.get_client_for_user(current_user, client_id, merchant_id=merchant_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    marked = mark_client_inbound_read(db, client.id, email_id=email_id)
    return MessageResponse(message=f"{marked} mensajes marcados como leídos")


@router.post("/{client_id}/resubmit", response_model=ClientResponse)
def resubmit_client(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:update"))],
    merchant_id: ActiveMerchantId,
) -> ClientResponse:
    service = ClientService(db)
    client = service.get_client_for_user(current_user, client_id, merchant_id=merchant_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client = service.resubmit_for_review(actor=current_user, client=client)
    return _to_response(client)


@router.post("/{client_id}/reject", response_model=ClientResponse)
def reject_client(
    client_id: int,
    payload: ClientReject,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:approve"))],
    merchant_id: ActiveMerchantId,
) -> ClientResponse:
    service = ClientService(db)
    if not service.user_can_access_client(current_user, client_id, merchant_id=merchant_id):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client = service.reject_client(actor=current_user, client=client, reason=payload.reason)
    return _to_response(client)


@router.delete("/{client_id}", response_model=MessageResponse)
def delete_client(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:delete"))],
    merchant_id: ActiveMerchantId,
) -> MessageResponse:
    return _delete_client(db, current_user, client_id, merchant_id)


@router.post("/{client_id}/delete", response_model=MessageResponse)
def delete_client_action(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:delete"))],
    merchant_id: ActiveMerchantId,
) -> MessageResponse:
    return _delete_client(db, current_user, client_id, merchant_id)


def _delete_client(
    db: DbSession,
    current_user: User,
    client_id: int,
    merchant_id: int,
) -> MessageResponse:
    service = ClientService(db)
    if not service.user_can_access_client(current_user, client_id, merchant_id=merchant_id):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    service.delete_client(actor=current_user, client=client)
    return MessageResponse(message="Cliente eliminado")


@router.post("/{client_id}/approve", response_model=ClientApproveResponse)
def approve_client(
    client_id: int,
    payload: ClientApprove,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:approve"))],
    merchant_id: ActiveMerchantId,
) -> ClientApproveResponse:
    del payload  # body vacío / advisor_user_id ignorado (compat)
    service = ClientService(db)
    if not service.user_can_access_client(current_user, client_id, merchant_id=merchant_id):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client, temp_password = service.approve_client(
        actor=current_user, client=client
    )
    return ClientApproveResponse(client=_to_response(client), temp_password=temp_password)


@router.patch("/{client_id}/advisor", response_model=AdvisorBrief)
def assign_client_advisor(
    client_id: int,
    payload: ClientAssignAdvisor,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:approve"))],
    merchant_id: ActiveMerchantId,
) -> AdvisorBrief:
    """Reemplaza todos los asesores por uno (uso onboarding). Preferir POST /advisors para agregar."""
    from app.services.role_access import can_manage_onboarding, is_advisor

    if not can_manage_onboarding(current_user) or is_advisor(current_user):
        raise HTTPException(status_code=403, detail="Solo onboarding puede reemplazar el asesor asignado")

    service = ClientService(db)
    if not service.user_can_access_client(current_user, client_id, merchant_id=merchant_id):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client = service.get_client_detail(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    advisor = service.reassign_advisor(
        actor=current_user,
        client=client,
        advisor_user_id=payload.advisor_user_id,
    )
    return AdvisorBrief(
        id=advisor.id,
        first_name=advisor.first_name,
        last_name=advisor.last_name,
        email=advisor.email,
    )


@router.post("/{client_id}/advisors", response_model=AdvisorBrief)
def add_client_advisor(
    client_id: int,
    payload: ClientAssignAdvisor,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
    merchant_id: ActiveMerchantId,
) -> AdvisorBrief:
    service = ClientService(db)
    if not service.user_can_access_client(current_user, client_id, merchant_id=merchant_id):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client = service.get_client_detail(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    service.require_can_manage_client_advisors(current_user, client)

    advisor = service.add_advisor(
        actor=current_user,
        client=client,
        advisor_user_id=payload.advisor_user_id,
    )
    return AdvisorBrief(
        id=advisor.id,
        first_name=advisor.first_name,
        last_name=advisor.last_name,
        email=advisor.email,
    )


@router.delete("/{client_id}/advisors/{advisor_user_id}", response_model=MessageResponse)
def remove_client_advisor(
    client_id: int,
    advisor_user_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
    merchant_id: ActiveMerchantId,
) -> MessageResponse:
    service = ClientService(db)
    if not service.user_can_access_client(current_user, client_id, merchant_id=merchant_id):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client = service.get_client_detail(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    service.require_can_manage_client_advisors(current_user, client)

    service.remove_advisor(
        actor=current_user,
        client=client,
        advisor_user_id=advisor_user_id,
    )
    return MessageResponse(message="Asesor desasignado")


@router.post("/{client_id}/reset-portal-password", response_model=ClientPortalPasswordResponse)
def reset_portal_password(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:approve"))],
    merchant_id: ActiveMerchantId,
) -> ClientPortalPasswordResponse:
    service = ClientService(db)
    client = service.get_client_for_user(current_user, client_id, merchant_id=merchant_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    email, temp_password, portal_login_url = service.reset_portal_password(
        actor=current_user,
        client=client,
    )
    return ClientPortalPasswordResponse(
        email=email,
        temp_password=temp_password,
        portal_login_url=portal_login_url,
    )
