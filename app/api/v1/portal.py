from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.deps import CurrentUser, DbSession
from app.models.address import Address
from app.models.client import Client
from app.models.document import Document
from app.models.enums import DocumentVerificationStatus
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.client import (
    AddressCreate,
    AddressResponse,
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
            )
            .where(Client.id == client_id)
        )
        .unique()
        .scalar_one_or_none()
    )


@router.get("/me", response_model=ClientDetailResponse)
def portal_me(current_user: CurrentUser, db: DbSession) -> ClientDetailResponse:
    client_id = _require_client_user(current_user)
    client = _load_client(db, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
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
    )
    db.refresh(client, attribute_names=["merchant"])
    return client_to_response(client)


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
        return AddressResponse.model_validate(existing)
    addr = Address(client_id=client_id, **payload.model_dump())
    db.add(addr)
    db.commit()
    db.refresh(addr)
    return AddressResponse.model_validate(addr)


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
        return VehicleResponse.model_validate(existing)
    vehicle = Vehicle(client_id=client_id, **payload.model_dump())
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return VehicleResponse.model_validate(vehicle)
