from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.deps import CurrentUser, DbSession
from app.models.address import Address
from app.models.client import Client
from app.models.client_assignment import ClientAssignment
from app.models.document import Document
from app.models.enums import ClientStatus, DocumentVerificationStatus
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.client import (
    AddressAutocompleteResponse,
    AddressCreate,
    AddressDetailsResponse,
    AddressResponse,
    AddressSuggestion,
    ClientDetailResponse,
    ClientResponse,
    ClientSsnResponse,
    DocumentBrief,
    ProfileUpdate,
    VehicleCreate,
    VehicleResponse,
)
from app.schemas.common import MessageResponse
from app.serializers.client import client_to_response
from app.services.address import AddressProviderError, get_address_provider
from app.services.client_onboarding_status import sync_client_onboarding_status
from app.services.clients import ClientService
from app.services.documents import DocumentService

router = APIRouter(prefix="/portal", tags=["Portal del cliente"])


def _require_client_user(user: User) -> int:
    if user.role.code != "CLIENT" or not user.client_id:
        raise HTTPException(status_code=403, detail="Acceso solo para clientes")
    return user.client_id


def _load_client(db, client_id: int) -> Client | None:
    return (
        db.execute(
            select(Client)
            .options(
                joinedload(Client.merchant),
                joinedload(Client.addresses),
                joinedload(Client.vehicles),
                joinedload(Client.documents).joinedload(Document.verifications),
                joinedload(Client.assignments).joinedload(ClientAssignment.advisor),
            )
            .where(Client.id == client_id)
        )
        .unique()
        .scalar_one_or_none()
    )


def _sync_and_commit_if_changed(db, client: Client) -> None:
    """Avanza onboarding (datos→docs→listo) si corresponde."""
    if client.status not in {
        ClientStatus.EN_CARGA_DATOS.value,
        ClientStatus.DOCUMENTOS_EN_REVISION.value,
    }:
        return
    if sync_client_onboarding_status(db, client):
        db.commit()
        db.refresh(client)


@router.get("/me", response_model=ClientDetailResponse)
def portal_me(current_user: CurrentUser, db: DbSession) -> ClientDetailResponse:
    client_id = _require_client_user(current_user)
    client = _load_client(db, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    _sync_and_commit_if_changed(db, client)
    client = _load_client(db, client_id) or client
    doc_service = DocumentService(db)
    base = client_to_response(client)
    return ClientDetailResponse(
        **base.model_dump(),
        addresses=[AddressResponse.model_validate(a) for a in client.addresses],
        vehicles=[VehicleResponse.model_validate(v) for v in client.vehicles],
        documents=[
            doc_service.to_brief(d, include_download_url=False) for d in client.documents
        ],
    )


@router.get("/documents", response_model=list[DocumentBrief])
def portal_documents(current_user: CurrentUser, db: DbSession) -> list[DocumentBrief]:
    client_id = _require_client_user(current_user)
    client = _load_client(db, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    doc_service = DocumentService(db)
    from app.workers.enqueue import enqueue_document_verification

    for doc in client.documents:
        if doc.verification_status == DocumentVerificationStatus.PENDIENTE.value:
            enqueue_document_verification(doc.id)
    return [doc_service.to_brief(d, include_download_url=True) for d in client.documents]


@router.get("/ssn", response_model=ClientSsnResponse)
def portal_ssn(current_user: CurrentUser, db: DbSession) -> ClientSsnResponse:
    client_id = _require_client_user(current_user)
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    service = ClientService(db)
    return ClientSsnResponse(ssn=service.get_client_ssn(client))


@router.patch("/profile", response_model=ClientResponse)
def update_profile(
    payload: ProfileUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> ClientResponse:
    client_id = _require_client_user(current_user)
    client = (
        db.execute(
            select(Client).options(joinedload(Client.merchant)).where(Client.id == client_id)
        )
        .unique()
        .scalar_one_or_none()
    )
    if client is None:
        raise HTTPException(status_code=404)
    service = ClientService(db)
    client = service.update_profile(
        actor=current_user,
        client=client,
        ssn=payload.ssn,
        date_of_birth=payload.date_of_birth,
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    _sync_and_commit_if_changed(db, client)
    db.refresh(client, attribute_names=["merchant"])
    return client_to_response(client)


@router.get("/addresses/autocomplete", response_model=AddressAutocompleteResponse)
def autocomplete_address(
    current_user: CurrentUser,
    q: str = Query(..., min_length=3, max_length=200, description="Texto a autocompletar"),
    session_token: str | None = Query(default=None, max_length=64),
) -> AddressAutocompleteResponse:
    """Sugiere direcciones reales mientras el cliente escribe."""
    _require_client_user(current_user)
    try:
        suggestions = get_address_provider().autocomplete(q, session_token=session_token)
    except AddressProviderError:
        # Degradación suave: si el proveedor falla, no bloqueamos la carga de datos.
        return AddressAutocompleteResponse(suggestions=[])
    return AddressAutocompleteResponse(
        suggestions=[
            AddressSuggestion(
                place_id=s.place_id,
                description=s.description,
                main_text=s.main_text,
                secondary_text=s.secondary_text,
                street=s.street,
                city=s.city,
                state=s.state,
                zip_code=s.zip_code,
            )
            for s in suggestions
        ]
    )


@router.get("/addresses/details", response_model=AddressDetailsResponse)
def address_details(
    current_user: CurrentUser,
    place_id: str = Query(..., min_length=1, max_length=300),
    session_token: str | None = Query(default=None, max_length=64),
) -> AddressDetailsResponse:
    """Devuelve los campos estructurados de una sugerencia que no vino resuelta."""
    _require_client_user(current_user)
    try:
        details = get_address_provider().place_details(place_id, session_token=session_token)
    except AddressProviderError as exc:
        raise HTTPException(status_code=exc.status_code or 502, detail=str(exc)) from exc
    return AddressDetailsResponse(
        place_id=details.place_id,
        formatted_address=details.formatted_address,
        street=details.street,
        city=details.city,
        state=details.state,
        zip_code=details.zip_code,
    )


@router.post("/addresses", response_model=AddressResponse, status_code=status.HTTP_201_CREATED)
def add_address(payload: AddressCreate, current_user: CurrentUser, db: DbSession) -> AddressResponse:
    client_id = _require_client_user(current_user)
    existing = db.execute(
        select(Address).where(Address.client_id == client_id, Address.type == payload.type)
    ).scalar_one_or_none()
    if existing:
        for field, value in payload.model_dump().items():
            setattr(existing, field, value)
        db.commit()
        db.refresh(existing)
    else:
        addr = Address(client_id=client_id, **payload.model_dump())
        db.add(addr)
        db.commit()
        db.refresh(addr)
        existing = addr

    client = db.get(Client, client_id)
    if client is not None:
        _sync_and_commit_if_changed(db, client)
    return AddressResponse.model_validate(existing)


@router.post("/vehicles", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
def add_vehicle(payload: VehicleCreate, current_user: CurrentUser, db: DbSession) -> VehicleResponse:
    client_id = _require_client_user(current_user)
    existing = db.execute(
        select(Vehicle).where(Vehicle.client_id == client_id, Vehicle.order == payload.order)
    ).scalar_one_or_none()
    if existing:
        for field, value in payload.model_dump().items():
            setattr(existing, field, value)
        db.commit()
        db.refresh(existing)
    else:
        vehicle = Vehicle(client_id=client_id, **payload.model_dump())
        db.add(vehicle)
        db.commit()
        db.refresh(vehicle)
        existing = vehicle

    client = db.get(Client, client_id)
    if client is not None:
        _sync_and_commit_if_changed(db, client)
    return VehicleResponse.model_validate(existing)
