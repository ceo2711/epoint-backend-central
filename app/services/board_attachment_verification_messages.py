"""Mensajes bilingües para verificación IA de adjuntos del tablero."""

from __future__ import annotations

from typing import Any

from app.services.document_verification_messages import (
    BilingualMessage,
    _msg,
    normalize_bilingual_messages,
)


def build_board_rejection_messages(
    result: dict[str, Any],
    *,
    attachment_kind: str,
    client_name: str,
) -> list[BilingualMessage]:
    from_ai = normalize_bilingual_messages(result.get("rejection_reasons"))
    if from_ai:
        return from_ai

    messages: list[BilingualMessage] = []
    if not result.get("is_readable", False):
        messages.append(
            _msg(
                "The file is not readable or is too blurry.",
                "El archivo no es legible o está demasiado borroso.",
            )
        )
    if not result.get("is_complete", False):
        messages.append(
            _msg(
                "The report appears incomplete or missing required sections.",
                "El reporte está incompleto o le faltan secciones requeridas.",
            )
        )
    if result.get("document_type_matches") is not True:
        detected = str(result.get("detected_document_type", "")).strip()
        bureau = str(result.get("detected_bureau", "")).strip()
        detail = detected or bureau
        if detail:
            messages.append(
                _msg(
                    f"The uploaded file is not the expected report ({attachment_kind}). Detected: {detail}.",
                    f"El archivo subido no es el reporte esperado ({attachment_kind}). Detectado: {detail}.",
                )
            )
        else:
            messages.append(
                _msg(
                    f"The uploaded file does not match the expected report type ({attachment_kind}).",
                    f"El archivo subido no coincide con el tipo de reporte esperado ({attachment_kind}).",
                )
            )
    if result.get("name_matches") is not True:
        messages.append(
            _msg(
                f"The client's name ({client_name}) was not found on the report.",
                f"No se encontró el nombre del cliente ({client_name}) en el reporte.",
            )
        )
    if result.get("is_recent") is not True:
        report_date = str(result.get("report_date", "")).strip()
        if report_date:
            messages.append(
                _msg(
                    f"The report date ({report_date}) is outdated. Only reports from the last 15 days are accepted — please upload a newly generated report.",
                    f"La fecha del reporte ({report_date}) está desactualizada. Solo se aceptan reportes de los últimos 15 días: sube un reporte recién generado.",
                )
            )
        else:
            messages.append(
                _msg(
                    "The report does not appear recent. Only reports from the last 15 days are accepted — please upload a newly generated report.",
                    "El reporte no parece reciente. Solo se aceptan reportes de los últimos 15 días: sube un reporte recién generado.",
                )
            )
    if not messages:
        messages.append(
            _msg(
                f"The file does not meet the requirements for {attachment_kind}.",
                f"El archivo no cumple los requisitos para {attachment_kind}.",
            )
        )
    return messages


def build_board_approval_messages(
    result: dict[str, Any],
    *,
    attachment_kind: str,
    client_name: str,
) -> list[BilingualMessage]:
    from_ai = normalize_bilingual_messages(result.get("approval_reasons"))
    if from_ai:
        return from_ai

    messages: list[BilingualMessage] = []
    if result.get("is_readable", False):
        messages.append(
            _msg(
                "The report is clear and readable.",
                "El reporte es claro y legible.",
            )
        )
    if result.get("document_type_matches") is True:
        detected = str(result.get("detected_document_type", "")).strip()
        bureau = str(result.get("detected_bureau", "")).strip()
        label = detected or bureau or attachment_kind
        messages.append(
            _msg(
                f"Report type verified: {label}.",
                f"Tipo de reporte verificado: {label}.",
            )
        )
    if result.get("name_matches") is True:
        messages.append(
            _msg(
                f"The client's name ({client_name}) matches the report.",
                f"El nombre del cliente ({client_name}) coincide con el reporte.",
            )
        )
    if result.get("is_recent") is True:
        report_date = str(result.get("report_date", "")).strip()
        if report_date:
            messages.append(
                _msg(
                    f"Report date verified: {report_date}.",
                    f"Fecha del reporte verificada: {report_date}.",
                )
            )
        else:
            messages.append(
                _msg(
                    "The report appears recent and valid.",
                    "El reporte parece reciente y válido.",
                )
            )
    if not messages:
        messages.append(
            _msg(
                "The file passed AI verification successfully.",
                "El archivo pasó la verificación de IA exitosamente.",
            )
        )
    return messages
