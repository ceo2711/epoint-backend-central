import re

# Conjugaciones rioplatenses: aprobar / aprueba / apruébalos / aprueben / etc.
_APPROVE_VERB = r"(?:aprobar|apru[eé]ba(?:r(?:me|nos)?)?(?:lo|la|los|las)?|apru[eé]be(?:s|n)?(?:lo|la|los|las)?)"
_REJECT_VERB = r"(?:rechazar|rechaz[aá](?:r(?:me|nos)?)?(?:lo|la|los|las)?|rechac[eé](?:s|n)?(?:lo|la|los|las)?)"
_ALL_TARGETS = r"(?:todos?|todas?)(?:\s+(?:los?\s+)?(?:clientes?\s+)?pendientes?)?"

APPROVE_ALL_PATTERN = re.compile(
    rf"(?:{_APPROVE_VERB}\s*(?:a\s+)?{_ALL_TARGETS}|{_ALL_TARGETS}\s+(?:los?\s+)?{_APPROVE_VERB})",
    re.IGNORECASE,
)

REJECT_ALL_PATTERN = re.compile(
    rf"(?:{_REJECT_VERB}\s*(?:a\s+)?{_ALL_TARGETS}|{_ALL_TARGETS}\s+(?:los?\s+)?{_REJECT_VERB})",
    re.IGNORECASE,
)

APPROVE_ONE_ID_PATTERN = re.compile(
    rf"{_APPROVE_VERB}(?:\s+(?:al?\s+)?cliente)?\s+#?(\d{{1,8}})\b",
    re.IGNORECASE,
)

REJECT_ONE_ID_PATTERN = re.compile(
    rf"{_REJECT_VERB}(?:\s+(?:al?\s+)?cliente)?\s+#?(\d{{1,8}})\b",
    re.IGNORECASE,
)

APPROVE_BY_NAME_PATTERN = re.compile(
    rf"{_APPROVE_VERB}\s+(?:a\s+)?(?!todos?\b)(?!todas?\b)",
    re.IGNORECASE,
)

REJECT_BY_NAME_PATTERN = re.compile(
    rf"{_REJECT_VERB}\s+(?:a\s+)?(?!todos?\b)(?!todas?\b)",
    re.IGNORECASE,
)


def looks_like_approve_all(message: str) -> bool:
    return bool(APPROVE_ALL_PATTERN.search(message))


def looks_like_reject_all(message: str) -> bool:
    return bool(REJECT_ALL_PATTERN.search(message))


def looks_like_approve_one(message: str) -> bool:
    if looks_like_approve_all(message):
        return False
    return bool(APPROVE_ONE_ID_PATTERN.search(message) or APPROVE_BY_NAME_PATTERN.search(message))


def looks_like_reject_one(message: str) -> bool:
    if looks_like_reject_all(message):
        return False
    return bool(REJECT_ONE_ID_PATTERN.search(message) or REJECT_BY_NAME_PATTERN.search(message))
