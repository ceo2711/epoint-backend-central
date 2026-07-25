"""API de subvendedores (equipo del vendedor elegible)."""

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.user import SubSellerActiveUpdate, SubSellerCreate, UserResponse
from app.services.sub_sellers import SubSellerService
from app.services.user_serialization import serialize_user

router = APIRouter(prefix="/sub-sellers", tags=["Subvendedores"])


@router.get("/eligibility")
def get_eligibility(current_user: CurrentUser, db: DbSession) -> dict:
    return SubSellerService(db).eligibility(current_user)


@router.get("/metrics")
def team_metrics(current_user: CurrentUser, db: DbSession) -> dict:
    return SubSellerService(db).team_metrics(current_user)


@router.get("", response_model=list[UserResponse])
def list_sub_sellers(current_user: CurrentUser, db: DbSession) -> list[UserResponse]:
    service = SubSellerService(db)
    return [serialize_user(u) for u in service.list_sub_sellers(current_user)]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_sub_seller(
    payload: SubSellerCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> UserResponse:
    user = SubSellerService(db).create_sub_seller(
        current_user,
        email=str(payload.email),
        password=payload.password,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
    )
    return serialize_user(user)


@router.patch("/{sub_seller_id}", response_model=UserResponse)
def update_sub_seller_active(
    sub_seller_id: int,
    payload: SubSellerActiveUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> UserResponse:
    user = SubSellerService(db).set_sub_seller_active(
        current_user,
        sub_seller_id,
        is_active=payload.is_active,
    )
    return serialize_user(user)
