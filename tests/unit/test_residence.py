from datetime import date

from app.services.residence import residence_less_than_two_years


def test_residence_less_than_two_years():
    today = date(2026, 8, 28)
    assert residence_less_than_two_years(8, 2025, today=today) is True
    assert residence_less_than_two_years(8, 2024, today=today) is False
    assert residence_less_than_two_years(None, 2025, today=today) is False
    assert residence_less_than_two_years(1, None, today=today) is False
