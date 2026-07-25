from typing import Any

from app.services.chatbot.messages import t


CLIENT_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "PENDIENTE_DE_REVISION": ("Pendiente de revisión", "Pending review"),
    "RECHAZADO": ("Rechazado", "Rejected"),
    "APROBADO_PARA_ONBOARDING": ("Aprobado para onboarding", "Approved for onboarding"),
    "EN_CARGA_DATOS": ("En carga de datos", "Loading data"),
    "DOCUMENTOS_EN_REVISION": ("Documentos en revisión", "Documents under review"),
    "LISTO_PARA_TRABAJAR": ("Listo para trabajar", "Ready to work"),
    "ONBOARDING_EN_PROGRESO": ("Onboarding en progreso", "Onboarding in progress"),
    "ONBOARDING_COMPLETADO": ("Onboarding completado", "Onboarding completed"),
    "INACTIVO": ("Inactivo", "Inactive"),
}

VERIFICATION_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "PENDIENTE": ("Pendiente", "Pending"),
    "EN_PROCESO": ("En proceso", "In progress"),
    "APROBADO": ("Aprobado", "Approved"),
    "RECHAZADO": ("Rechazado", "Rejected"),
    "PROXIMO_A_VENCER": ("Próximo a vencer", "Expiring soon"),
    "FALTANTE": ("No subido", "Not uploaded"),
}

TASK_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "PENDIENTE": ("Pendiente", "Pending"),
    "EN_PROGRESO": ("En progreso", "In progress"),
    "EN_REVISION": ("En revisión", "Under review"),
    "COMPLETADA": ("Completada", "Completed"),
}


def _label(mapping: dict[str, tuple[str, str]], key: str, locale: str) -> str:
    es, en = mapping.get(key, (key, key))
    return es if locale.lower().startswith("es") else en


def _document_line(doc: dict[str, Any], locale: str) -> str:
    doc_status = _label(VERIFICATION_STATUS_LABELS, str(doc.get("estado_verificacion", "")), locale)
    line = f"- **{doc.get('tipo')}**: {doc_status}"
    if not doc.get("subido"):
        return line + "\n"
    rejection = _localized_reasons(doc.get("motivos_rechazo"), locale)
    if doc.get("estado_verificacion") == "RECHAZADO" and rejection:
        line += f" — {t(locale, 'Motivo', 'Reason')}: {rejection}"
    elif doc.get("estado_verificacion") == "APROBADO":
        approval = _localized_reasons(doc.get("motivos_aprobacion"), locale)
        if approval:
            line += f" — {approval}"
    return line + "\n"


def _append_documents_report(parts: list[str], detail: dict[str, Any], locale: str) -> None:
    docs_payload = detail.get("documentos") or {}
    legacy_docs = detail.get("documentos_requeridos") or []
    if legacy_docs:
        for doc in legacy_docs:
            parts.append(_document_line(doc, locale))
        return

    ssn = docs_payload.get("ssn")
    if ssn:
        parts.append(_document_line(ssn, locale))

    for section_key, section_title in (
        ("identidad", t(locale, "Identidad", "Identity")),
        ("comprobante_domicilio", t(locale, "Comprobante de domicilio", "Proof of address")),
    ):
        section = docs_payload.get(section_key) or {}
        if not section:
            continue
        parts.append(f"\n**{section_title}** — {section.get('instruccion', '')}\n")
        for option in section.get("opciones") or []:
            marker = "✅" if option.get("completa") else "○"
            parts.append(f"{marker} {option.get('opcion')}:\n")
            for doc in option.get("documentos") or []:
                parts.append(_document_line(doc, locale))


def _localized_reasons(reasons: dict[str, Any] | None, locale: str) -> str | None:
    if not reasons:
        return None
    lang = "es" if locale.lower().startswith("es") else "en"
    items = reasons.get(lang) or reasons.get("es") or reasons.get("en") or []
    if not items:
        return None
    return "; ".join(str(item) for item in items)


def format_pending_approval_answer(locale: str, pending: list[dict[str, Any]]) -> str:
    if not pending:
        return t(
            locale,
            "No hay clientes pendientes de revisión en este momento.",
            "There are no clients pending review at the moment.",
        )

    ready = [item for item in pending if item.get("listo_para_aprobar")]
    not_ready = [item for item in pending if not item.get("listo_para_aprobar")]

    parts = [
        t(
            locale,
            f"Hay **{len(pending)}** cliente(s) pendiente(s) de revisión.\n",
            f"There are **{len(pending)}** client(s) pending review.\n",
        ),
        t(
            locale,
            "_Para aprobar solo se necesitan: nombre completo, email, teléfono, fuente y comercio. "
            "Documentos y datos de perfil se completan después de la aprobación._\n",
            "_To approve you only need: full name, email, phone, source and merchant. "
            "Documents and profile data are completed after approval._\n",
        ),
    ]

    if ready:
        parts.append(
            t(locale, f"✅ **Listos para aprobar** ({len(ready)}):\n", f"✅ **Ready to approve** ({len(ready)}):\n")
        )
        for item in ready:
            parts.append(f"- **{item['nombre']}** (ID {item['id']})\n")
        parts.append("\n")

    if not_ready:
        parts.append(
            t(
                locale,
                f"⚠️ **Faltan datos para aprobar** ({len(not_ready)}):\n",
                f"⚠️ **Missing data to approve** ({len(not_ready)}):\n",
            )
        )
        for item in not_ready:
            problems = ", ".join(item.get("problemas_aprobacion") or [])
            parts.append(f"- **{item['nombre']}** (ID {item['id']}): {problems}\n")

    parts.append(
        t(
            locale,
            "\nSi querés, decime por ejemplo: *aprobar a [nombre]*, *aprobar todos* o *informe de [nombre]*.",
            "\nYou can say: *approve [name]*, *approve all*, or *report for [name]*.",
        )
    )
    return "".join(parts)


def format_client_report(locale: str, detail: dict[str, Any]) -> str:
    name = detail.get("nombre", "?")
    client_id = detail.get("id", "?")
    status = _label(CLIENT_STATUS_LABELS, str(detail.get("estado", "")), locale)

    parts = [
        t(locale, f"## Informe de **{name}** (ID {client_id})\n\n", f"## Report for **{name}** (ID {client_id})\n\n"),
        t(locale, "### Datos básicos\n", "### Basic data\n"),
        f"- {t(locale, 'Email', 'Email')}: {detail.get('email') or '—'}\n",
        f"- {t(locale, 'Teléfono', 'Phone')}: {detail.get('telefono') or '—'}\n",
        f"- {t(locale, 'Estado', 'Status')}: {status}\n",
    ]

    if detail.get("fuente"):
        parts.append(f"- {t(locale, 'Fuente', 'Source')}: {detail.get('fuente_label') or detail.get('fuente')}\n")
    if detail.get("comercio"):
        parts.append(f"- {t(locale, 'Comercio', 'Merchant')}: {detail.get('comercio')}\n")

    if detail.get("aprobado"):
        parts.append(f"- {t(locale, 'Aprobado', 'Approved')}: ✅\n")
    elif detail.get("motivo_rechazo"):
        parts.append(
            f"- {t(locale, 'Rechazado', 'Rejected')}: ❌ — {detail.get('motivo_rechazo')}\n"
        )

    approval_problems = detail.get("problemas_aprobacion") or []
    if detail.get("estado") == "PENDIENTE_DE_REVISION":
        if approval_problems:
            parts.append(
                f"- {t(locale, 'Listo para aprobar', 'Ready to approve')}: ❌ ({', '.join(approval_problems)})\n"
            )
        else:
            parts.append(f"- {t(locale, 'Listo para aprobar', 'Ready to approve')}: ✅\n")

    onboarding_gaps = detail.get("pendientes_onboarding") or []
    if onboarding_gaps:
        parts.append(
            f"\n{t(locale, '### Pendientes de onboarding (post-aprobación)', '### Post-approval onboarding pending')}\n"
        )
        for gap in onboarding_gaps:
            parts.append(f"- {gap}\n")

    parts.append(f"\n{t(locale, '### Documentos', '### Documents')}\n")
    _append_documents_report(parts, detail, locale)

    extra_docs = detail.get("documentos_adicionales") or []
    if extra_docs:
        parts.append(f"\n{t(locale, '**Documentos adicionales:**', '**Additional documents:**')}\n")
        for doc in extra_docs:
            doc_status = _label(VERIFICATION_STATUS_LABELS, str(doc.get("estado_verificacion", "")), locale)
            parts.append(f"- {doc.get('tipo')}: {doc_status}\n")

    board = detail.get("tablero")
    parts.append(f"\n{t(locale, '### Tablero de onboarding', '### Onboarding board')}\n")
    if not board or not board.get("existe"):
        parts.append(t(locale, "El cliente aún no tiene tablero.\n", "This client does not have a board yet.\n"))
    else:
        summary = board.get("resumen") or {}
        parts.append(
            t(
                locale,
                f"Tarjetas: **{summary.get('total_tarjetas', 0)}** total — "
                f"**{summary.get('completadas', 0)}** completadas, "
                f"**{summary.get('pendientes', 0)}** pendientes.\n\n",
                f"Cards: **{summary.get('total_tarjetas', 0)}** total — "
                f"**{summary.get('completadas', 0)}** completed, "
                f"**{summary.get('pendientes', 0)}** pending.\n\n",
            )
        )
        for column in board.get("columnas") or []:
            parts.append(f"**{column.get('columna')}**\n")
            for card in column.get("tarjetas") or []:
                card_status = _label(TASK_STATUS_LABELS, str(card.get("estado", "")), locale)
                flags: list[str] = []
                if card.get("requiere_archivo"):
                    flags.append(t(locale, "archivo", "file"))
                if card.get("requiere_credenciales"):
                    flags.append(t(locale, "credenciales", "credentials"))
                suffix = f" ({', '.join(flags)})" if flags else ""
                parts.append(f"- {card.get('titulo')}: _{card_status}_{suffix}\n")
            parts.append("\n")

    return "".join(parts).strip()
