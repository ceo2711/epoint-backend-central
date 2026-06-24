import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select

from app.api.deps import DbSession, require_permissions
from app.models.client import Client
from app.models.user import User
from app.schemas.client import (
    ClientApprove,
    ClientApproveResponse,
    ClientAssignAdvisor,
    ClientAvailabilityResponse,
    ClientCreate,
    ClientDetailResponse,
    ClientPortalPasswordResponse,
    ClientReject,
    ClientResponse,
    ClientStatsResponse,
    ClientUpdate,
    AdvisorBrief,
)
from app.schemas.common import MessageResponse, PaginatedResponse
from app.serializers.client import client_to_response
from app.services.clients import ClientService
from app.services.documents import DocumentService

router = APIRouter(prefix="/clients", tags=["Clientes"])


def _to_response(client: Client) -> ClientResponse:
    return client_to_response(client)


@router.get("", response_model=PaginatedResponse[ClientResponse])
def list_clients(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = None,
    search: str | None = None,
    onboarding_only: bool = Query(False),
) -> PaginatedResponse[ClientResponse]:
    service = ClientService(db)
    clients, total = service.list_clients_for_user(
        current_user,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        search=search,
        onboarding_only=onboarding_only,
    )
    return PaginatedResponse(
        items=[_to_response(c) for c in clients],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


@router.get("/check-availability", response_model=ClientAvailabilityResponse)
def check_client_availability(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:create"))],
    email: str | None = Query(default=None),
    phone: str | None = Query(default=None),
    exclude_client_id: int | None = Query(default=None),
) -> ClientAvailabilityResponse:
    service = ClientService(db)
    result = service.check_contact_availability(
        email=email,
        phone=phone,
        exclude_client_id=exclude_client_id,
    )
    return ClientAvailabilityResponse(**result)


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientCreate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:create"))],
) -> ClientResponse:
    service = ClientService(db)
    client = service.create_client(
        actor=current_user,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=str(payload.email),
        phone=payload.phone,
        source=payload.source.value,
        merchant_id=payload.merchant_id,
    )
    db.refresh(client, attribute_names=["merchant"])
    return _to_response(client)


@router.get("/stats", response_model=ClientStatsResponse)
def get_client_stats(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
) -> ClientStatsResponse:
    service = ClientService(db)
    return ClientStatsResponse(**service.get_client_stats(current_user))


@router.get("/{client_id}", response_model=ClientDetailResponse)
def get_client(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
) -> ClientDetailResponse:
    service = ClientService(db)
    if not service.user_can_access_client(current_user, client_id):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client = service.get_client_detail(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    base = _to_response(client)
    portal = service.get_portal_access_info(client)
    doc_service = DocumentService(db)
    latest_verifications = doc_service.load_latest_verifications_map([doc.id for doc in client.documents])
    advisor_brief: AdvisorBrief | None = None
    if current_user.role.code in ("ONBOARDING_MANAGER", "ADMIN"):
        active_advisor = service._get_active_advisor(client)
        if active_advisor is not None:
            advisor_brief = AdvisorBrief(
                id=active_advisor.id,
                first_name=active_advisor.first_name,
                last_name=active_advisor.last_name,
                email=active_advisor.email,
            )
    return ClientDetailResponse(
        **base.model_dump(),
        **portal,
        advisor=advisor_brief,
        addresses=client.addresses,
        vehicles=client.vehicles,
        documents=[
            doc_service.to_brief(
                doc,
                include_download_url=False,
                latest_verification=latest_verifications.get(doc.id),
            )
            for doc in client.documents
        ],
    )


@router.patch("/{client_id}", response_model=ClientResponse)
def update_client(
    client_id: int,
    payload: ClientUpdate,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:update"))],
) -> ClientResponse:
    service = ClientService(db)
    client = service.get_client_for_user(current_user, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client = service.update_client(actor=current_user, client=client, **payload.model_dump(exclude_unset=True))
    db.refresh(client, attribute_names=["merchant"])
    return _to_response(client)


@router.post("/{client_id}/resubmit", response_model=ClientResponse)
def resubmit_client(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:update"))],
) -> ClientResponse:
    service = ClientService(db)
    client = service.get_client_for_user(current_user, client_id)
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
) -> ClientResponse:
    service = ClientService(db)
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
) -> MessageResponse:
    return _delete_client(db, current_user, client_id)


@router.post("/{client_id}/delete", response_model=MessageResponse)
def delete_client_action(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:delete"))],
) -> MessageResponse:
    return _delete_client(db, current_user, client_id)


def _delete_client(db: DbSession, current_user: User, client_id: int) -> MessageResponse:
    service = ClientService(db)
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
) -> ClientApproveResponse:
    service = ClientService(db)
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    client, temp_password = service.approve_client(
        actor=current_user, client=client, advisor_user_id=payload.advisor_user_id
    )
    return ClientApproveResponse(client=_to_response(client), temp_password=temp_password)


@router.patch("/{client_id}/advisor", response_model=AdvisorBrief)
def assign_client_advisor(
    client_id: int,
    payload: ClientAssignAdvisor,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:approve"))],
) -> AdvisorBrief:
    if current_user.role.code not in ("ONBOARDING_MANAGER", "ADMIN"):
        raise HTTPException(status_code=403, detail="Solo onboarding puede gestionar el asesor asignado")

    service = ClientService(db)
    client = service.get_client_detail(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    if not service.user_can_access_client(current_user, client_id):
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


@router.post("/{client_id}/reset-portal-password", response_model=ClientPortalPasswordResponse)
def reset_portal_password(
    client_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:approve"))],
) -> ClientPortalPasswordResponse:
    service = ClientService(db)
    client = service.get_client_for_user(current_user, client_id)
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
