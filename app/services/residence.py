"""Helpers de antigüedad de residencia para onboarding."""

from __future__ import annotations

from datetime import date


def residence_less_than_two_years(
    month: int | None,
    year: int | None,
    *,
    today: date | None = None,
) -> bool:
    """True si el mes/año de mudanza indica menos de 24 meses en esa dirección."""
    if not month or not year:
        return False
    today = today or date.today()
    months = (today.year - year) * 12 + (today.month - month)
    return months < 24
