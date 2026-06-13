from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.deps import CurrentUser, DbSession
from app.models.address import Address
from app.models.client import Client
from app.models.enums import DocumentVerificationStatus
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.client import (
    AddressCreate,
    AddressResponse,
    ClientDetailResponse,
    ClientResponse,
    DocumentBrief,
    ProfileUpdate,
    VehicleCreate,
    VehicleResponse,
)
from app.schemas.common import MessageResponse
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
                joinedload(Client.addresses),
                joinedload(Client.vehicles),
                joinedload(Client.documents),
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
    return ClientDetailResponse(
        id=client.id,
        status=client.status,
        first_name=client.first_name,
        last_name=client.last_name,
        email=client.email,
        phone=client.phone,
        rejection_reason=client.rejection_reason,
        rejected_at=client.rejected_at,
        approved_at=client.approved_at,
        date_of_birth=client.date_of_birth,
        has_ssn=bool(client.ssn_encrypted),
        registered_by_user_id=client.registered_by_user_id,
        created_at=client.created_at,
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


@router.patch("/profile", response_model=ClientResponse)
def update_profile(
    payload: ProfileUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> ClientResponse:
    client_id = _require_client_user(current_user)
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404)
    service = ClientService(db)
    client = service.update_profile(
        actor=current_user,
        client=client,
        ssn=payload.ssn,
        date_of_birth=payload.date_of_birth,
    )
    return ClientResponse(
        id=client.id,
        status=client.status,
        first_name=client.first_name,
        last_name=client.last_name,
        email=client.email,
        phone=client.phone,
        rejection_reason=client.rejection_reason,
        rejected_at=client.rejected_at,
        approved_at=client.approved_at,
        date_of_birth=client.date_of_birth,
        has_ssn=bool(client.ssn_encrypted),
        registered_by_user_id=client.registered_by_user_id,
        created_at=client.created_at,
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
