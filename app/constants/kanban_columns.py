"""Columnas estándar del tablero Kanban por cliente."""

PERSONAL_FUNDING_SEQUENCE = "Personal Funding Sequence"
PERSONAL_FUNDING_SEQUENCE_2 = "Personal Funding Sequence (2)"
BUSINESS_FUNDING_SEQUENCE = "Business Funding Sequence"
BUSINESS_FUNDING_SEQUENCE_2 = "Business Funding Sequence (2)"
COMPLETED_LIST_TITLE = "Completed"

KANBAN_COLUMN_TITLES: tuple[str, ...] = (
    "Client TO DO",
    "Pendientes EpointCredits",
    "Ideas a realizar",
    "Credenciales",
    "Experian",
    "Transunion",
    "Equifax",
    "Cuentas de banco",
    PERSONAL_FUNDING_SEQUENCE,
    PERSONAL_FUNDING_SEQUENCE_2,
    BUSINESS_FUNDING_SEQUENCE,
    BUSINESS_FUNDING_SEQUENCE_2,
    COMPLETED_LIST_TITLE,
)

FUNDING_SEQUENCE_TITLES: frozenset[str] = frozenset(
    {
        PERSONAL_FUNDING_SEQUENCE,
        PERSONAL_FUNDING_SEQUENCE_2,
        BUSINESS_FUNDING_SEQUENCE,
        BUSINESS_FUNDING_SEQUENCE_2,
    }
)

# Renombres de columnas legacy (typos / copy viejo) → título canónico.
KANBAN_COLUMN_TITLE_ALIASES: dict[str, str] = {
    "Pendientes EpointCredints": "Pendientes EpointCredits",
    "Pendientes EpointCredicts": "Pendientes EpointCredits",
    "Personal Fonding Sequence": PERSONAL_FUNDING_SEQUENCE,
    "Personal Fonding Sequence (2)": PERSONAL_FUNDING_SEQUENCE_2,
    "Business Founding Sequence": BUSINESS_FUNDING_SEQUENCE,
    "Business Founding Sequence (2)": BUSINESS_FUNDING_SEQUENCE_2,
}


def canonical_column_title(title: str | None) -> str:
    raw = (title or "").strip()
    return KANBAN_COLUMN_TITLE_ALIASES.get(raw, raw)


def is_funding_sequence_column(title: str | None) -> bool:
    return canonical_column_title(title) in FUNDING_SEQUENCE_TITLES


def funding_sequence_title_variants() -> frozenset[str]:
    titles = set(FUNDING_SEQUENCE_TITLES)
    for alias, canonical in KANBAN_COLUMN_TITLE_ALIASES.items():
        if canonical in FUNDING_SEQUENCE_TITLES:
            titles.add(alias)
    return frozenset(titles)


def is_completed_column(title: str | None) -> bool:
    return canonical_column_title(title) == COMPLETED_LIST_TITLE
