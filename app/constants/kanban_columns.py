"""Columnas estándar del tablero Kanban por cliente."""

KANBAN_COLUMN_TITLES: tuple[str, ...] = (
    "Client TO DO",
    "Pendientes EpointCredits",
    "Ideas a realizar",
    "Credenciales",
    "Experian",
    "Transunion",
    "Equifax",
    "Cuentas de banco",
    "Personal Fonding Sequence",
    "Personal Fonding Sequence (2)",
    "Business Founding Sequence",
    "Business Founding Sequence (2)",
    "Completed",
)

# Renombres de columnas legacy (typos / copy viejo) → título canónico.
KANBAN_COLUMN_TITLE_ALIASES: dict[str, str] = {
    "Pendientes EpointCredints": "Pendientes EpointCredits",
    "Pendientes EpointCredicts": "Pendientes EpointCredits",
}
