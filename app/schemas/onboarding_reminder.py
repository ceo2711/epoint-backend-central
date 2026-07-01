from pydantic import BaseModel


class OnboardingReminderConfigResponse(BaseModel):
    interval_minutes: int
    cooldown_hours: int
    automatic_enabled: bool
    dry_run: bool


class OnboardingReminderRunResponse(BaseModel):
    processed: int
    sent: int
    skipped: int
    skipped_cooldown: int = 0
    failed: int
    dry_run: bool = False
    skipped_concurrent: bool = False
