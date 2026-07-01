import re

LIST_EVENTS_PATTERN = re.compile(
    r"(?:mis\s+)?(?:reuniones?|reuniones|citas?|eventos?\s+(?:del?\s+)?calendario)"
    r"|(?:agenda|calendario)\s+(?:de\s+)?(?:hoy|manana|mañana|semana)"
    r"|(?:que\s+tengo|qué\s+tengo)\s+(?:hoy|manana|mañana)"
    r"|(?:reuniones?\s+de\s+hoy|today'?s?\s+(?:meetings?|events?))",
    re.IGNORECASE,
)

CREATE_EVENT_PATTERN = re.compile(
    r"(?:agendar|crear|programar|reservar|schedule|book)\s+(?:una\s+)?(?:reunion|reunión|cita|meeting|evento)",
    re.IGNORECASE,
)

CANCEL_EVENT_PATTERN = re.compile(
    r"(?:cancelar|eliminar|borrar|anular)\s+(?:la\s+)?(?:reunion|reunión|cita|meeting|evento)",
    re.IGNORECASE,
)

EDIT_EVENT_PATTERN = re.compile(
    r"(?:editar|modificar|reprogramar|mover|cambiar)\s+(?:la\s+)?(?:reunion|reunión|cita|meeting|evento)",
    re.IGNORECASE,
)

CONFIRM_PATTERN = re.compile(
    r"^(?:confirmar|confirm|si|sí|yes|ok|dale|listo)(?:\s|$)",
    re.IGNORECASE,
)

EVENT_ID_PATTERN = re.compile(
    r"(?:reunion|reunión|cita|evento|meeting)?\s*#?(\d{1,8})\b",
    re.IGNORECASE,
)

OPTION_NUMBER_PATTERN = re.compile(r"^#?(\d{1,2})$")

TIME_PATTERN = re.compile(r"(\d{1,2}:\d{2}(?:\s*[ap]\.?m\.?)?)", re.IGNORECASE)
