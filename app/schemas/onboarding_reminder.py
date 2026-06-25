from pydantic import BaseModel


class OnboardingReminderConfigResponse(BaseModel):
    interval_minutes: int
    automatic_enabled: bool
    dry_run: bool


class OnboardingReminderRunResponse(BaseModel):
    processed: int
    sent: int
    skipped: int
    failed: int
    dry_run: bool = False
