from app.core.phone import (
    format_twilio_whatsapp_from,
    normalize_whatsapp_number,
    phones_match,
)


class TestNormalizeWhatsappNumber:
    def test_local_argentina_number(self):
        assert normalize_whatsapp_number("1131432490") == "+5491131432490"

    def test_already_e164_argentina(self):
        assert normalize_whatsapp_number("+5491131432490") == "+5491131432490"

    def test_landline_adds_mobile_prefix(self):
        assert normalize_whatsapp_number("+541112345678") == "+5491112345678"

    def test_with_whatsapp_prefix_stripped_in_match(self):
        assert phones_match("whatsapp:+5491131432490", "+5491131432490")


class TestFormatTwilioWhatsappFrom:
    def test_adds_whatsapp_prefix(self):
        result = format_twilio_whatsapp_from("1131432490")
        assert result == "whatsapp:+5491131432490"

    def test_idempotent_if_already_prefixed(self):
        original = "whatsapp:+5491131432490"
        assert format_twilio_whatsapp_from(original) == original
