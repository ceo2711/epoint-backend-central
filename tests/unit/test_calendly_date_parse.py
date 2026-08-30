from app.services.chatbot.calendly_options import parse_date_input


def test_parse_date_input_prefers_mm_dd():
    assert parse_date_input("08/29/2026") == "2026-08-29"
    assert parse_date_input("8/9/2026") == "2026-08-09"


def test_parse_date_input_falls_back_when_first_number_is_not_a_month():
    assert parse_date_input("29/08/2026") == "2026-08-29"


def test_parse_date_input_iso_and_relative():
    assert parse_date_input("2026-08-29") == "2026-08-29"
    assert parse_date_input("hoy") is not None
    assert parse_date_input("tomorrow") is not None
