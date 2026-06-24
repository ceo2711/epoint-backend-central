import re

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"\+?[\d][\d\s\-()]{7,}[\d]")

REGISTER_INTENT_PATTERN = re.compile(
    r"(?:quiero\s+)?(?:registrar|crear|agregar|dar\s+de\s+alta|cargar|nuevo|alta\s+de)\b",
    re.IGNORECASE,
)

REGISTER_META_QUERY_PATTERN = re.compile(
    r"(?:"
    r"(?:puedo|podes|pod[eé]s|puede(?:s)?|se\s+puede|hay\s+forma|sab[eé]s\s+si|me\s+podes|me\s+pod[eé]s)"
    r".{0,80}(?:registrar|registro|crear|agregar|dar\s+de\s+alta).{0,80}(?:varios?|varias?|m[uú]ltiples?|m[aá]s\s+de\s+uno|"
    r"al\s+mismo\s+tiempo|a\s+la\s+vez|seguidos?|uno\s+tras\s+otro|several|multiple|at\s+once)"
    r"|(?:varios?|varias?|m[uú]ltiples?).{0,40}(?:registrar|registro|crear|agregar).{0,40}(?:clientes?|al\s+mismo\s+tiempo|a\s+la\s+vez)"
    r"|(?:can\s+(?:i|you|we)|is\s+it\s+possible).{0,80}(?:register|create|add).{0,80}(?:multiple|several|at\s+once|same\s+time)"
    r")",
    re.IGNORECASE,
)

REGISTER_CAPABILITY_QUESTION_PATTERN = re.compile(
    r"(?:^|\b)(?:puedo|podes|pod[eé]s|puede(?:s)?|c[oó]mo|como|se\s+puede|hay\s+forma|"
    r"can\s+(?:i|you)|how\s+(?:do\s+i|can\s+i|to))\b",
    re.IGNORECASE,
)

NAME_STOPWORDS = frozenset(
    {
        "a",
        "al",
        "chat",
        "cliente",
        "clientes",
        "como",
        "cómo",
        "crear",
        "dar",
        "de",
        "el",
        "la",
        "las",
        "lo",
        "los",
        "mismo",
        "necesito",
        "puede",
        "puedes",
        "podés",
        "puedo",
        "quiero",
        "registrar",
        "registro",
        "several",
        "tiempo",
        "un",
        "una",
        "uno",
        "varias",
        "varios",
        "vez",
        "al",
        "misma",
        "mismo",
        "register",
        "multiple",
        "same",
        "time",
        "add",
        "create",
    }
)


def message_has_contact_data(message: str) -> bool:
    return bool(EMAIL_PATTERN.search(message) or PHONE_PATTERN.search(message))


def is_registration_meta_question(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    if REGISTER_META_QUERY_PATTERN.search(text):
        return True
    if "?" not in text:
        return False
    if not REGISTER_CAPABILITY_QUESTION_PATTERN.search(text):
        return False
    if not REGISTER_INTENT_PATTERN.search(text) and not re.search(
        r"\b(?:registrar|registro|crear\s+cliente|agregar\s+cliente|register\s+client)\b",
        text,
        re.IGNORECASE,
    ):
        return False
    return not message_has_contact_data(text)


def looks_like_person_name(first: str | None, last: str | None) -> bool:
    if not first or not last:
        return False
    first_clean = first.strip().lower()
    if first_clean in NAME_STOPWORDS or len(first_clean) < 2:
        return False
    for part in last.strip().lower().split():
        if part in NAME_STOPWORDS:
            return False
        if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", part):
            return False
    if len(last.strip().split()) > 4:
        return False
    return True
