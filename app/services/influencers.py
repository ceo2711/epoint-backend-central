from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.influencer import Influencer
from app.models.user import User
from app.services.role_access import SALES_STAFF_ROLES, is_sales_area_leader
from app.services.sede_scope import effective_sede_id

INFLUENCERS_SOURCE_CODE = "INFLUENCERS"


def can_manage_influencers(user: User) -> bool:
    return is_sales_area_leader(user)


def require_influencer_manager(user: User) -> None:
    if not can_manage_influencers(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el jefe de área de ventas puede administrar influencers",
        )


def _validate_sales_rep(db: Session, *, sales_rep_user_id: int, sede_id: int) -> User:
    rep = (
        db.execute(
            select(User)
            .options(joinedload(User.role), joinedload(User.sede))
            .where(User.id == sales_rep_user_id)
        )
        .unique()
        .scalar_one_or_none()
    )
    if rep is None or not rep.is_active or rep.role.code not in SALES_STAFF_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vendedor inválido")
    if rep.sede_id != sede_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El vendedor no pertenece a esa sede",
        )
    return rep


def resolve_influencer_sede_id(actor: User, sede_id: int | None) -> int:
    actor_sede = effective_sede_id(actor)
    if actor_sede is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu usuario no tiene sede asignada",
        )
    if sede_id is not None and sede_id != actor_sede:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No podés administrar influencers de otra sede",
        )
    return actor_sede


def list_influencers(
    db: Session,
    actor: User,
    *,
    include_inactive: bool = False,
    sede_id: int | None = None,
) -> list[Influencer]:
    query = (
        select(Influencer)
        .options(
            joinedload(Influencer.sales_rep),
            joinedload(Influencer.sede),
        )
        .order_by(Influencer.name)
    )
    scope = effective_sede_id(actor)
    if scope is not None:
        query = query.where(Influencer.sede_id == scope)
    elif sede_id is not None:
        query = query.where(Influencer.sede_id == sede_id)
    if not include_inactive:
        query = query.where(Influencer.is_active.is_(True))
    return list(db.execute(query).unique().scalars().all())


def list_influencer_options(
    db: Session,
    actor: User,
    *,
    sede_id: int | None = None,
) -> list[Influencer]:
    """Activos de la sede efectiva (admin puede filtrar por sede)."""
    query = (
        select(Influencer)
        .options(joinedload(Influencer.sales_rep))
        .where(Influencer.is_active.is_(True))
        .order_by(Influencer.name)
    )
    scope = effective_sede_id(actor)
    if scope is not None:
        query = query.where(Influencer.sede_id == scope)
    elif sede_id is not None:
        query = query.where(Influencer.sede_id == sede_id)
    return list(db.execute(query).unique().scalars().all())


def create_influencer(
    db: Session,
    *,
    actor: User,
    name: str,
    sales_rep_user_id: int,
    handle: str | None = None,
    notes: str | None = None,
    sede_id: int | None = None,
) -> Influencer:
    require_influencer_manager(actor)
    resolved_sede_id = resolve_influencer_sede_id(actor, sede_id)
    _validate_sales_rep(db, sales_rep_user_id=sales_rep_user_id, sede_id=resolved_sede_id)

    influencer = Influencer(
        name=name.strip(),
        handle=handle.strip() if handle else None,
        notes=notes.strip() if notes else None,
        sede_id=resolved_sede_id,
        sales_rep_user_id=sales_rep_user_id,
        created_by_user_id=actor.id,
        is_active=True,
    )
    db.add(influencer)
    db.commit()
    db.refresh(influencer)
    return (
        db.execute(
            select(Influencer)
            .options(joinedload(Influencer.sales_rep), joinedload(Influencer.sede))
            .where(Influencer.id == influencer.id)
        )
        .unique()
        .scalar_one()
    )


def update_influencer(
    db: Session,
    *,
    actor: User,
    influencer: Influencer,
    name: str | None = None,
    handle: str | None = None,
    notes: str | None = None,
    sales_rep_user_id: int | None = None,
    is_active: bool | None = None,
) -> Influencer:
    require_influencer_manager(actor)
    scope = effective_sede_id(actor)
    if scope is not None and influencer.sede_id != scope:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Influencer no encontrado")

    if name is not None:
        influencer.name = name.strip()
    if handle is not None:
        influencer.handle = handle.strip() or None
    if notes is not None:
        influencer.notes = notes.strip() or None
    if sales_rep_user_id is not None:
        _validate_sales_rep(db, sales_rep_user_id=sales_rep_user_id, sede_id=influencer.sede_id)
        influencer.sales_rep_user_id = sales_rep_user_id
    if is_active is not None:
        influencer.is_active = is_active

    db.commit()
    db.refresh(influencer)
    return (
        db.execute(
            select(Influencer)
            .options(joinedload(Influencer.sales_rep), joinedload(Influencer.sede))
            .where(Influencer.id == influencer.id)
        )
        .unique()
        .scalar_one()
    )


def get_influencer_for_actor(db: Session, actor: User, influencer_id: int) -> Influencer:
    influencer = (
        db.execute(
            select(Influencer)
            .options(joinedload(Influencer.sales_rep), joinedload(Influencer.sede))
            .where(Influencer.id == influencer_id)
        )
        .unique()
        .scalar_one_or_none()
    )
    if influencer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Influencer no encontrado")
    scope = effective_sede_id(actor)
    if scope is not None and influencer.sede_id != scope:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Influencer no encontrado")
    return influencer


def resolve_prospect_influencer_id(
    db: Session,
    *,
    source: str | None,
    influencer_id: int | None,
    sede_id: int,
) -> int | None:
    """Si source es INFLUENCERS exige un influencer activo de la sede; si no, limpia el FK."""
    if source != INFLUENCERS_SOURCE_CODE:
        return None
    if influencer_id is None:
        raise ValueError("Debés seleccionar un influencer")
    influencer = db.get(Influencer, influencer_id)
    if (
        influencer is None
        or not influencer.is_active
        or influencer.sede_id != sede_id
    ):
        raise ValueError("Influencer inválido para esta sede")
    return influencer.id
