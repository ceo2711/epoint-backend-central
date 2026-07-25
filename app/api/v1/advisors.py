from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession, require_permissions
from app.models.role import Role
from app.models.user import User
from app.schemas.client import AdvisorBrief

router = APIRouter(prefix="/advisors", tags=["Asesores"])

_ADVISOR_LIST_ROLES = frozenset({"ONBOARDING_MANAGER", "ADMIN", "BRANCH_MANAGER", "ADVISOR"})


@router.get("", response_model=list[AdvisorBrief])
def list_advisors(
    db: DbSession,
    current_user: Annotated[User, Depends(require_permissions("clients:read"))],
) -> list[AdvisorBrief]:
    if current_user.role.code not in _ADVISOR_LIST_ROLES:
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
