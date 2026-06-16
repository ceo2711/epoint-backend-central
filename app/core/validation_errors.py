"""Mensajes legibles para errores de validación de Pydantic/FastAPI."""

from __future__ import annotations

FIELD_LABELS: dict[str, str] = {
    "ssn": "Número de Seguro Social (SSN)",
    "date_of_birth": "Fecha de nacimiento",
    "email": "Correo electrónico",
    "password": "Contraseña",
    "first_name": "Nombre",
    "last_name": "Apellido",
    "phone": "Teléfono",
    "street": "Calle",
    "city": "Ciudad",
    "state": "Estado",
    "zip_code": "Código postal",
    "model": "Modelo del vehículo",
    "year": "Año",
    "color": "Color",
    "reason": "Motivo",
}

EXPLICIT_MESSAGES: dict[tuple[str, str], str] = {
    ("string_too_short", "ssn"): "El número de Seguro Social debe tener 9 dígitos (formato XXX-XX-XXXX).",
    ("string_too_long", "ssn"): "El número de Seguro Social no puede tener más de 11 caracteres.",
    ("missing", "date_of_birth"): "Ingresá tu fecha de nacimiento.",
    ("date_parsing", "date_of_birth"): "La fecha de nacimiento no es válida.",
    ("string_too_short", "password"): "La contraseña debe tener al menos 8 caracteres.",
}


def _field_name(loc: tuple[str | int, ...]) -> str:
    if not loc:
        return ""
    return str(loc[-1])


def humanize_validation_error(error: dict) -> str:
    err_type = error.get("type", "")
    field = _field_name(tuple(error.get("loc", ())))
    label = FIELD_LABELS.get(field, field.replace("_", " ").capitalize() if field else "Campo")

    explicit = EXPLICIT_MESSAGES.get((err_type, field))
    if explicit:
        return explicit

    if err_type == "value_error":
        msg = str(error.get("msg", ""))
        return msg.removeprefix("Value error, ")

    ctx = error.get("ctx") or {}

    if err_type == "string_too_short":
        min_length = ctx.get("min_length")
        if field == "ssn":
            return "El número de Seguro Social debe tener 9 dígitos (formato XXX-XX-XXXX)."
        if min_length:
            return f"{label}: debe tener al menos {min_length} caracteres."
        return f"{label}: el valor es demasiado corto."

    if err_type == "string_too_long":
        max_length = ctx.get("max_length")
        if max_length:
            return f"{label}: no puede superar {max_length} caracteres."
        return f"{label}: el valor es demasiado largo."

    if err_type == "missing":
        return f"Ingresá {label.lower()}." if label else "Completá los campos obligatorios."

    if err_type in {"date_parsing", "datetime_parsing"}:
        return f"{label}: ingresá una fecha válida."

    if err_type == "int_parsing":
        return f"{label}: debe ser un número entero."

    if err_type == "greater_than_equal":
        limit = ctx.get("ge")
        return f"{label}: debe ser mayor o igual a {limit}."

    if err_type == "less_than_equal":
        limit = ctx.get("le")
        return f"{label}: debe ser menor o igual a {limit}."

    if err_type == "value_error.email" or err_type.endswith("email"):
        return "Ingresá un correo electrónico válido."

    msg = str(error.get("msg", "")).strip()
    if msg:
        return msg

    return "Revisá los datos ingresados e intentá de nuevo."


def humanize_validation_errors(errors: list[dict]) -> str:
    if not errors:
        return "Revisá los datos ingresados e intentá de nuevo."
    messages = [humanize_validation_error(err) for err in errors]
    # Quitar duplicados preservando orden
    unique: list[str] = []
    for message in messages:
        if message not in unique:
            unique.append(message)
    return " ".join(unique)
