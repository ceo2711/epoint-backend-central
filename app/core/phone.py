import re


def _ensure_argentina_mobile(e164: str) -> str:
    """WhatsApp/Twilio en Argentina usa móvil +549XX..., no +5411..."""
    if not e164.startswith("+54"):
        return e164
    rest = e164[3:]
    if rest.startswith("9"):
        return e164
    return f"+549{rest}"


def normalize_whatsapp_number(phone: str, default_country_code: str = "54") -> str:
    """Normaliza teléfono a formato E.164 (+54911...) para WhatsApp/Twilio."""
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return phone

    if phone.strip().startswith("+"):
        normalized = f"+{digits}"
        if default_country_code == "54":
            normalized = _ensure_argentina_mobile(normalized)
        return normalized

    if digits.startswith(default_country_code):
        national = digits[len(default_country_code) :]
        if national.startswith("0"):
            national = national[1:]
        normalized = f"+{default_country_code}{national}"
        if default_country_code == "54":
            normalized = _ensure_argentina_mobile(normalized)
        return normalized

    if default_country_code == "54" and digits.startswith("0"):
        digits = digits[1:]

    normalized = f"+{default_country_code}{digits}"
    if default_country_code == "54":
        normalized = _ensure_argentina_mobile(normalized)
    return normalized


def phones_match(a: str, b: str, default_country_code: str = "54") -> bool:
    """Compara dos teléfonos normalizados (sin prefijo whatsapp:)."""
    na = normalize_whatsapp_number(a.replace("whatsapp:", ""), default_country_code)
    nb = normalize_whatsapp_number(b.replace("whatsapp:", ""), default_country_code)
    return na == nb


def format_twilio_whatsapp_from(phone: str, default_country_code: str = "54") -> str:
    """Formato remitente Twilio: whatsapp:+5491131432490"""
    normalized = normalize_whatsapp_number(phone, default_country_code)
    if normalized.startswith("whatsapp:"):
        return normalized
    return f"whatsapp:{normalized}"
