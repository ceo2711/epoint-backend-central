from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession, require_any_permissions
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.influencer import (
    InfluencerBrief,
    InfluencerCreate,
    InfluencerResponse,
    InfluencerUpdate,
)
from app.services import influencers as influencer_service

router = APIRouter(prefix="/influencers", tags=["Influencers"])


def _to_response(row) -> InfluencerResponse:
    sales_rep = row.sales_rep
    sede = row.sede
    return InfluencerResponse(
        id=row.id,
        name=row.name,
        handle=row.handle,
        notes=row.notes,
        sede_id=row.sede_id,
        sede_name=sede.name if sede else None,
        sales_rep_user_id=row.sales_rep_user_id,
        sales_rep_name=f"{sales_rep.first_name} {sales_rep.last_name}".strip() if sales_rep else None,
        is_active=row.is_active,
        created_at=row.created_at,
    )


def _to_brief(row) -> InfluencerBrief:
    sales_rep = row.sales_rep
    return InfluencerBrief(
        id=row.id,
        name=row.name,
        handle=row.handle,
        sales_rep_user_id=row.sales_rep_user_id,
        sales_rep_name=f"{sales_rep.first_name} {sales_rep.last_name}".strip() if sales_rep else None,
    )


@router.get("/options", response_model=list[InfluencerBrief])
def list_influencer_options(
    db: DbSession,
    current_user: Annotated[
        User,
        Depends(require_any_permissions("prospects:create", "prospects:update")),
    ],
    sede_id: int | None = Query(default=None),
) -> list[InfluencerBrief]:
    rows = influencer_service.list_influencer_options(db, current_user, sede_id=sede_id)
    return [_to_brief(row) for row in rows]


@router.get("", response_model=list[InfluencerResponse])
def list_influencers(
    db: DbSession,
    current_user: CurrentUser,
    include_inactive: bool = False,
    sede_id: int | None = Query(default=None),
) -> list[InfluencerResponse]:
    influencer_service.require_influencer_manager(current_user)
    rows = influencer_service.list_influencers(
        db,
        current_user,
        include_inactive=include_inactive,
        sede_id=sede_id,
    )
    return [_to_response(row) for row in rows]


@router.post("", response_model=InfluencerResponse, status_code=status.HTTP_201_CREATED)
def create_influencer(
    payload: InfluencerCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> InfluencerResponse:
    row = influencer_service.create_influencer(
        db,
        actor=current_user,
        name=payload.name,
        handle=payload.handle,
        notes=payload.notes,
        sales_rep_user_id=payload.sales_rep_user_id,
        sede_id=payload.sede_id,
    )
    return _to_response(row)


@router.patch("/{influencer_id}", response_model=InfluencerResponse)
def update_influencer(
    influencer_id: int,
    payload: InfluencerUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> InfluencerResponse:
    row = influencer_service.get_influencer_for_actor(db, current_user, influencer_id)
    row = influencer_service.update_influencer(
        db,
        actor=current_user,
        influencer=row,
        **payload.model_dump(exclude_unset=True),
    )
    return _to_response(row)


@router.delete("/{influencer_id}", response_model=MessageResponse)
def deactivate_influencer(
    influencer_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> MessageResponse:
    row = influencer_service.get_influencer_for_actor(db, current_user, influencer_id)
    influencer_service.update_influencer(
        db,
        actor=current_user,
        influencer=row,
        is_active=False,
    )
    return MessageResponse(message="Influencer desactivado")
