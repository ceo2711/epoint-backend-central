"""Mensajes bilingües para resultados de verificación IA de documentos."""

from __future__ import annotations

from typing import Any

from app.services.document_verification_rules import requires_name_match

BilingualMessage = dict[str, str]


def _msg(en: str, es: str) -> BilingualMessage:
    return {"en": en, "es": es}


def normalize_bilingual_messages(raw: Any) -> list[BilingualMessage]:
    if not raw:
        return []
    if not isinstance(raw, list):
        return []

    normalized: list[BilingualMessage] = []
    for item in raw:
        if isinstance(item, dict) and item.get("en") and item.get("es"):
            normalized.append({"en": str(item["en"]).strip(), "es": str(item["es"]).strip()})
        elif isinstance(item, str) and item.strip():
            text = item.strip()
            normalized.append({"en": text, "es": text})
    return normalized


def to_localized_lists(messages: list[BilingualMessage]) -> dict[str, list[str]]:
    return {
        "en": [item["en"] for item in messages],
        "es": [item["es"] for item in messages],
    }


def build_rejection_messages(
    result: dict[str, Any],
    *,
    document_type: str,
    client_name: str,
) -> list[BilingualMessage]:
    from_ai = normalize_bilingual_messages(result.get("rejection_reasons"))
    if from_ai:
        return from_ai

    messages: list[BilingualMessage] = []
    if not result.get("is_readable", False):
        messages.append(
            _msg(
                "The document is not readable or is too blurry.",
                "El documento no es legible o está demasiado borroso.",
            )
        )
    if not result.get("is_complete", False):
        messages.append(
            _msg(
                "The document appears incomplete or missing required information.",
                "El documento está incompleto o le falta información requerida.",
            )
        )
    if not result.get("is_color", False):
        messages.append(
            _msg(
                "The document must be submitted in color.",
                "El documento debe subirse a color.",
            )
        )
    if result.get("corners_cut", False):
        messages.append(
            _msg(
                "The document has cropped or cut corners.",
                "El documento tiene esquinas cortadas.",
            )
        )
    if result.get("is_expired", False):
        messages.append(
            _msg(
                "The document is expired or no longer valid.",
                "El documento está vencido o ya no es válido.",
            )
        )
    if result.get("document_type_matches") is not True:
        detected = str(result.get("detected_document_type", "")).strip()
        if detected:
            messages.append(
                _msg(
                    f"The uploaded file is not a {document_type}. Detected: {detected}.",
                    f"El archivo subido no es un {document_type}. Detectado: {detected}.",
                )
            )
        else:
            messages.append(
                _msg(
                    f"The uploaded file is not the required document type ({document_type}).",
                    f"El archivo subido no es el tipo de documento requerido ({document_type}).",
                )
            )
    if requires_name_match(document_type) and result.get("name_matches") is not True:
        messages.append(
            _msg(
                f"The client's name ({client_name}) was not found on the document.",
                f"No se encontró el nombre del cliente ({client_name}) en el documento.",
            )
        )
    if document_type in ("UTILITY_BILL", "BANK_STATEMENT") and not result.get("address_matches", False):
        messages.append(
            _msg(
                "The address on the document does not match the client's current address.",
                "La dirección del documento no coincide con la dirección actual del cliente.",
            )
        )
    if not messages:
        messages.append(
            _msg(
                f"The document does not meet the requirements for {document_type}.",
                f"El documento no cumple los requisitos para {document_type}.",
            )
        )
    return messages


def build_approval_messages(
    result: dict[str, Any],
    *,
    document_type: str,
    client_name: str,
    expires_at: str | None = None,
) -> list[BilingualMessage]:
    from_ai = normalize_bilingual_messages(result.get("approval_reasons"))
    if from_ai:
        return from_ai

    messages: list[BilingualMessage] = []
    if result.get("is_readable", False):
        messages.append(
            _msg(
                "The document is clear and readable.",
                "El documento es claro y legible.",
            )
        )
    if result.get("is_complete", False):
        messages.append(
            _msg(
                "The document includes the required information.",
                "El documento incluye la información requerida.",
            )
        )
    if result.get("is_color", False):
        messages.append(
            _msg(
                "The document was submitted in color.",
                "El documento fue enviado a color.",
            )
        )
    if not result.get("corners_cut", True):
        messages.append(
            _msg(
                "All corners are visible and none appear cropped.",
                "Todas las esquinas son visibles y no aparecen cortadas.",
            )
        )
    if not result.get("is_expired", True):
        messages.append(
            _msg(
                "The document is valid and not expired.",
                "El documento está vigente y no se encuentra vencido.",
            )
        )
    if result.get("document_type_matches") is True:
        detected = str(result.get("detected_document_type", "")).strip()
        if detected:
            messages.append(
                _msg(
                    f"Document type verified: {detected} matches the expected upload ({document_type}).",
                    f"Tipo de documento verificado: {detected} coincide con el esperado ({document_type}).",
                )
            )
        else:
            messages.append(
                _msg(
                    f"The document type matches the expected upload ({document_type}).",
                    f"El tipo de documento coincide con el esperado ({document_type}).",
                )
            )
    if requires_name_match(document_type) and result.get("name_matches") is True:
        messages.append(
            _msg(
                f"The client's name ({client_name}) matches the document.",
                f"El nombre del cliente ({client_name}) coincide con el documento.",
            )
        )
    if document_type in ("UTILITY_BILL", "BANK_STATEMENT"):
        if result.get("address_matches", False):
            messages.append(
                _msg(
                    "The address on the document matches the client's current address.",
                    "La dirección del documento coincide con la dirección actual del cliente.",
                )
            )
    if expires_at:
        messages.append(
            _msg(
                f"Expiration date detected: {expires_at}.",
                f"Fecha de vencimiento detectada: {expires_at}.",
            )
        )
    if not messages:
        messages.append(
            _msg(
                "The document passed AI verification successfully.",
                "El documento pasó la verificación de IA exitosamente.",
            )
        )
    return messages
