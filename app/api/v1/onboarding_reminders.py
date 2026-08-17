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

def require_onboarding_reminder_staff(current_user: CurrentUser) -> User:
    from app.services.role_access import can_run_onboarding_reminders

    if not can_run_onboarding_reminders(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores y líderes de onboarding pueden ejecutar recordatorios",
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
        automatic_enabled=interval > 0,
        dry_run=settings.notifications_dry_run,
    )


@router.post("/run", response_model=OnboardingReminderRunResponse)
def run_onboarding_reminders_now(
    db: DbSession,
    current_user: Annotated[User, Depends(require_onboarding_reminder_staff)],
) -> OnboardingReminderRunResponse:
    result = run_onboarding_reminders(db)
    return OnboardingReminderRunResponse(**result)
