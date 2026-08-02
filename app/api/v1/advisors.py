from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession, require_permissions
from app.models.role import Role
from app.models.user import User
from app.schemas.client import AdvisorBrief

router = APIRouter(prefix="/advisors", tags=["Asesores"])

@router.get("", response_model=list[AdvisorBrief])
def list_advisors(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
) -> list[AdvisorBrief]:
    from app.services.role_access import (
        can_manage_onboarding,
        is_advisors_area_leader,
    )

    if not (
        can_manage_onboarding(current_user)
        or is_advisors_area_leader(current_user)
        or current_user.role.code == "ADVISOR"
    ):
        raise HTTPException(status_code=403, detail="No autorizado a listar asesores")

    advisors = (
        db.execute(
            select(User)
            .join(Role)
            .where(Role.code == "ADVISOR", User.is_active.is_(True))
            .order_by(User.first_name, User.last_name)
        )
        .scalars()
        .all()
    )
    return [
        AdvisorBrief(id=u.id, first_name=u.first_name, last_name=u.last_name, email=u.email)
        for u in advisors
    ]
