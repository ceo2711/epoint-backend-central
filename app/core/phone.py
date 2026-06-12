import re


def normalize_whatsapp_number(phone: str, default_country_code: str = "54") -> str:
    """Normaliza teléfono a formato E.164 (+54911...) para WhatsApp/Twilio."""
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return phone

    if phone.strip().startswith("+"):
        return f"+{digits}"

    # Ya incluye código de país (ej. 5401131432490 → +541131432490)
    if digits.startswith(default_country_code):
        national = digits[len(default_country_code) :]
        if national.startswith("0"):
            national = national[1:]
        return f"+{default_country_code}{national}"

    # Número local argentino (ej. 1131432490)
    if default_country_code == "54" and digits.startswith("0"):
        digits = digits[1:]

    return f"+{default_country_code}{digits}"


def phones_match(a: str, b: str, default_country_code: str = "54") -> bool:
    """Compara dos teléfonos normalizados (sin prefijo whatsapp:)."""
    na = normalize_whatsapp_number(a.replace("whatsapp:", ""), default_country_code)
    nb = normalize_whatsapp_number(b.replace("whatsapp:", ""), default_country_code)
    return na == nb


def format_twilio_whatsapp_from(phone: str, default_country_code: str = "54") -> str:
    """Formato remitente Twilio: whatsapp:+541131432490"""
    normalized = normalize_whatsapp_number(phone, default_country_code)
    if normalized.startswith("whatsapp:"):
        return normalized
    return f"whatsapp:{normalized}"
