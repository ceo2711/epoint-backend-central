import re

SPANISH_SWITCH_PATTERN = re.compile(
    r"(?:"
    r"(?:habl[aá]|respond[eé]|escrib[ií]|contest[aá]|hablame|háblame)"
    r".{0,35}(?:en\s+)?(?:español|castellano)"
    r"|(?:en\s+)?(?:español|castellano)(?:\s+por\s+favor)?"
    r"|quiero\s+(?:que\s+)?(?:hables|hable|respondas)\s+en\s+español"
    r")",
    re.IGNORECASE,
)

ENGLISH_SWITCH_PATTERN = re.compile(
    r"(?:"
    r"(?:speak|talk|write|reply|respond)"
    r".{0,25}english"
    r"|in\s+english"
    r"|english\s+please"
    r"|(?:i\s+)?want\s+english"
    r")",
    re.IGNORECASE,
)

LOCALE_ONLY_PATTERN = re.compile(
    r"^(?:"
    r"(?:por\s+favor\s+)?(?:habl[aá]|respond[eé]|escrib[ií])\s+(?:en\s+)?(?:español|castellano|english)"
    r"|(?:en\s+)?(?:español|castellano|english)\s+por\s+favor"
    r"|(?:please\s+)?(?:speak|talk|write|reply)\s+(?:in\s+)?english"
    r"|in\s+english\s+please"
    r")[.!?\s]*$",
    re.IGNORECASE,
)

SPANISH_HINTS = re.compile(
    r"\b(?:hola|qué|que|como|cómo|cuál|cuales|registra|registrar|cliente|gracias|"
    r"por\s+favor|ayuda|puedes|podés|necesito|aprueba|rechaza|pendientes|español)\b",
    re.IGNORECASE,
)

ENGLISH_HINTS = re.compile(
    r"\b(?:hello|hi|what|how|register|client|please|thanks|help|can\s+you|"
    r"approve|reject|pending|english|speak)\b",
    re.IGNORECASE,
)


def normalize_locale(locale: str | None) -> str:
    if locale and locale.lower().startswith("en"):
        return "en"
    return "es"


def detect_explicit_locale_switch(message: str) -> str | None:
    if SPANISH_SWITCH_PATTERN.search(message):
        return "es"
    if ENGLISH_SWITCH_PATTERN.search(message):
        return "en"
    return None


def infer_locale_from_message(message: str) -> str | None:
    spanish_score = len(SPANISH_HINTS.findall(message))
    english_score = len(ENGLISH_HINTS.findall(message))
    if spanish_score > english_score and spanish_score > 0:
        return "es"
    if english_score > spanish_score and english_score > 0:
        return "en"
    if re.search(r"[áéíóúñ¿¡]", message, re.IGNORECASE):
        return "es"
    return None


def is_locale_switch_request(message: str) -> bool:
    if not detect_explicit_locale_switch(message):
        return False
    from app.services.chatbot.actions import REGISTER_INTENT_PATTERN

    if REGISTER_INTENT_PATTERN.search(message):
        return False
    return True


def resolve_chat_locale(
    message: str,
    *,
    chat_locale: str | None,
    fallback_locale: str,
) -> str:
    explicit = detect_explicit_locale_switch(message)
    if explicit:
        return explicit

    inferred = infer_locale_from_message(message)
    if inferred:
        return inferred

    return normalize_locale(chat_locale or fallback_locale)
