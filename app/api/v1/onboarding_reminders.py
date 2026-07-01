from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.models.user import User
from app.schemas.onboarding_reminder import (
    OnboardingReminderConfigResponse,
    OnboardingReminderRunResponse,
)
from app.services.onboarding_reminders import run_onboarding_reminders

router = APIRouter(prefix="/onboarding-reminders", tags=["Recordatorios onboarding"])

ONBOARDING_REMINDER_ROLES = frozenset({"ADMIN", "ONBOARDING_MANAGER"})


def require_onboarding_reminder_staff(current_user: CurrentUser) -> User:
    if current_user.role.code not in ONBOARDING_REMINDER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores y onboarding pueden ejecutar recordatorios",
        )
    return current_user


@router.get("/config", response_model=OnboardingReminderConfigResponse)
def get_onboarding_reminders_config(
    current_user: Annotated[User, Depends(require_onboarding_reminder_staff)],
) -> OnboardingReminderConfigResponse:
    settings = get_settings()
    interval = settings.onboarding_reminder_interval_minutes
    return OnboardingReminderConfigResponse(
        interval_minutes=interval,
        cooldown_hours=settings.onboarding_reminder_cooldown_hours,
        automatic_enabled=interval > 0,
        dry_run=settings.notifications_dry_run,
    )


@router.post("/run", response_model=OnboardingReminderRunResponse)
def run_onboarding_reminders_now(
    db: DbSession,
    current_user: Annotated[User, Depends(require_onboarding_reminder_staff)],
    force: bool = False,
) -> OnboardingReminderRunResponse:
    result = run_onboarding_reminders(db, respect_cooldown=not force)
    return OnboardingReminderRunResponse(**result)
