from typing import Any

from app.models.merchant import Merchant
from app.services.chatbot.registration_options import (
    format_merchant_options,
    format_source_options,
    source_label,
)


def t(locale: str, es: str, en: str) -> str:
    return en if locale.lower().startswith("en") else es


def friendly_locale_switch(locale: str) -> str:
    return t(
        locale,
        "¡Perfecto! A partir de ahora te hablo en **español**. 🇦🇷",
        "Got it! From now on I'll speak **English**. 🇺🇸",
    )


def friendly_cancel(locale: str) -> str:
    return t(locale, "Listo, lo cancelamos. ¿En qué más te puedo ayudar? 😊", "Done, cancelled. What else can I help you with?")


def friendly_register_success(
    locale: str,
    *,
    full_name: str,
    client_id: int,
    email: str,
    phone: str,
    source: str | None = None,
    merchant_name: str | None = None,
    include_continue_prompt: bool = False,
) -> str:
    source_line = ""
    merchant_line = ""
    if source:
        source_line = f"\n- {t(locale, 'Fuente', 'Source')}: {source_label(source, locale)}"
    if merchant_name:
        merchant_line = f"\n- {t(locale, 'Comercio', 'Merchant')}: {merchant_name}"
    base = t(
        locale,
        (
            f"¡Listo! 🎉 Ya registré a **{full_name}**.\n\n"
            f"- Email: {email}\n"
            f"- Teléfono: {phone}{source_line}{merchant_line}\n\n"
            "Quedó **pendiente de revisión** por el equipo de onboarding."
        ),
        (
            f"Done! **{full_name}** has been registered.\n\n"
            f"- Email: {email}\n"
            f"- Phone: {phone}{source_line}{merchant_line}\n\n"
            "Status: **pending review**."
        ),
    )
    if include_continue_prompt:
        base += friendly_register_continue_prompt(locale)
    return base


def friendly_register_continue_prompt(locale: str) -> str:
    return t(
        locale,
        (
            "\n\n¿Querés registrar **otro cliente**? "
            "Mandame los datos del siguiente, o pegá varios bloques juntos con el formato "
            "*(Datos personales / Nombre completo / Email / Teléfono / merchant)*."
        ),
        (
            "\n\nWant to register **another client**? "
            "Send the next client's details, or paste several blocks at once using "
            "*(Personal data / Full name / Email / Phone / merchant)*."
        ),
    )


def friendly_registration_meta_reply(locale: str) -> str:
    return t(
        locale,
        (
            "Sí, podés registrar **varios clientes seguidos** en esta conversación. "
            "Cuando termino de cargar uno, te pido los datos del siguiente.\n\n"
            "También podés pegar **varios en un solo mensaje** con este formato:\n\n"
            "```\nDatos personales\n"
            "Nombre completo: Juan Pérez\n"
            "Email: juan@mail.com\n"
            "Numero de telefono: 1134567890\n"
            "merchant: db-studio\n```\n\n"
            "Repetí el bloque por cada cliente. Cada uno necesita **email y teléfono únicos**."
        ),
        (
            "Yes, you can register **multiple clients in a row** in this chat. "
            "After each one is saved, I'll ask for the next.\n\n"
            "You can also paste **several in one message** like this:\n\n"
            "```\nPersonal data\n"
            "Full name: John Doe\n"
            "Email: john@mail.com\n"
            "Phone number: 5551234567\n"
            "merchant: db-studio\n```\n\n"
            "Repeat the block for each client. Each one needs a **unique email and phone**."
        ),
    )


def friendly_register_missing(
    locale: str,
    draft: dict[str, Any],
    merchants: list[Merchant] | None = None,
) -> str:
    first = str(draft.get("first_name") or "").strip()
    last = str(draft.get("last_name") or "").strip()
    name = f"{first} {last}".strip()
    has_email = bool(draft.get("email"))
    has_phone = bool(draft.get("phone"))

    if name and has_email and has_phone and not draft.get("source"):
        return t(
            locale,
            (
                f"¡Excelente! Ya tengo los datos de contacto de **{name}**.\n\n"
                f"¿De qué **fuente** proviene? Estas son las opciones:\n\n"
                f"{format_source_options(locale)}\n\n"
                "Decime el nombre de la fuente (por ejemplo: WhatsApp o Página web)."
            ),
            (
                f"Great! I have **{name}**'s contact details.\n\n"
                f"What's the **source**? Available options:\n\n"
                f"{format_source_options(locale)}\n\n"
                "Tell me the source name (e.g. WhatsApp or Website)."
            ),
        )
    if name and has_email and has_phone and draft.get("source") and not draft.get("merchant_id"):
        merchant_block = format_merchant_options(locale, merchants or [])
        return t(
            locale,
            (
                f"Perfecto. ¿A qué **comercio / empresa** corresponde **{name}**?\n\n"
                f"Opciones disponibles:\n\n{merchant_block}\n\n"
                "Decime el nombre o código del comercio (por ejemplo: epoint-lab)."
            ),
            (
                f"Got it. Which **merchant / company** is **{name}** for?\n\n"
                f"Available options:\n\n{merchant_block}\n\n"
                "Tell me the merchant name or code (e.g. epoint-lab)."
            ),
        )

    if name and not has_email and not has_phone:
        return t(
            locale,
            f"¡Perfecto! Ya tengo a **{name}**. ¿Me pasás su **email** y **teléfono**?",
            f"Great! I have **{name}**. What's their **email** and **phone number**?",
        )
    if name and has_email and not has_phone:
        return t(
            locale,
            f"Genial, ya tengo el email de **{name}**. ¿Cuál es su **teléfono**?",
            f"Got the email for **{name}**. What's their **phone number**?",
        )
    if name and has_phone and not has_email:
        return t(
            locale,
            f"Ya tengo el teléfono de **{name}**. ¿Cuál es su **email**?",
            f"Got the phone for **{name}**. What's their **email**?",
        )
    if first and not last:
        return t(
            locale,
            f"Tengo el nombre **{first}**. ¿Cuál es su **apellido**?",
            f"I have the first name **{first}**. What's their **last name**?",
        )
    if not first and not last:
        return t(
            locale,
            "¡Con gusto te ayudo a registrar un cliente! ¿Cómo se llama? (nombre y apellido)",
            "Happy to help you register a client! What's their full name?",
        )

    missing_labels_es: list[str] = []
    missing_labels_en: list[str] = []
    if not first:
        missing_labels_es.append("nombre")
        missing_labels_en.append("first name")
    if not last:
        missing_labels_es.append("apellido")
        missing_labels_en.append("last name")
    if not has_email:
        missing_labels_es.append("email")
        missing_labels_en.append("email")
    if not has_phone:
        missing_labels_es.append("teléfono")
        missing_labels_en.append("phone")
    if not draft.get("source"):
        missing_labels_es.append("fuente")
        missing_labels_en.append("source")
    if not draft.get("merchant_id"):
        missing_labels_es.append("comercio")
        missing_labels_en.append("merchant")

    extra = ""
    if not draft.get("source"):
        extra += f"\n\n{t(locale, 'Fuentes disponibles', 'Available sources')}:\n{format_source_options(locale)}"
    if not draft.get("merchant_id") and merchants:
        extra += f"\n\n{t(locale, 'Comercios disponibles', 'Available merchants')}:\n{format_merchant_options(locale, merchants)}"

    return t(
        locale,
        f"Me faltan algunos datos: **{', '.join(missing_labels_es)}**. ¿Me los compartís?{extra}",
        f"I still need: **{', '.join(missing_labels_en)}**. Could you share them?{extra}",
    )


def friendly_register_error(locale: str, detail: str) -> str:
    return t(
        locale,
        f"Uy, no pude completar el registro: {detail}. ¿Querés revisar los datos e intentar de nuevo?",
        f"I couldn't complete the registration: {detail}. Want to try again?",
    )


def friendly_bulk_register_result(
    locale: str,
    *,
    successes: list[tuple[str, int, str, str]],
    failures: list[tuple[str, str]],
) -> str:
    parts: list[str] = []

    if successes:
        lines = [
            f"- **{name}** (#{client_id}) — {email} / {phone}"
            for name, client_id, email, phone in successes
        ]
        parts.append(
            t(
                locale,
                f"✅ **Registrados ({len(successes)}):**\n" + "\n".join(lines),
                f"✅ **Registered ({len(successes)}):**\n" + "\n".join(lines),
            )
        )

    if failures:
        lines = [f"- **{name}**: {reason}" for name, reason in failures]
        parts.append(
            t(
                locale,
                f"❌ **No se pudieron registrar ({len(failures)}):**\n" + "\n".join(lines),
                f"❌ **Could not register ({len(failures)}):**\n" + "\n".join(lines),
            )
        )

    if not successes and not failures:
        return t(
            locale,
            "No encontré clientes para registrar en ese mensaje.",
            "I couldn't find any clients to register in that message.",
        )

    summary = "\n\n".join(parts)
    if failures and any("email" in reason.lower() or "teléfono" in reason.lower() or "phone" in reason.lower() for _, reason in failures):
        summary += t(
            locale,
            "\n\n_Recordá que cada cliente debe tener un **email** y un **teléfono** únicos._",
            "\n\n_Remember each client must have a unique **email** and **phone number**._",
        )

    if successes:
        summary += friendly_register_continue_prompt(locale)

    return summary


def friendly_advisor_prompt(locale: str, lines: list[str]) -> str:
    body = "\n".join(lines)
    return t(
        locale,
        f"¿A qué **asesor** lo asignamos? Podés decirme el nombre o el email:\n\n{body}",
        f"Which **advisor** should we assign? Tell me their name or email:\n\n{body}",
    )


def friendly_approve_one_intro(locale: str, *, full_name: str, issues: list[str]) -> str:
    warning = ""
    if issues:
        warning = t(
            locale,
            f"\n\n⚠️ Ojo: vi algunos datos para revisar: {', '.join(issues)}.",
            f"\n\n⚠️ Note: some data may need review: {', '.join(issues)}.",
        )
    return t(
        locale,
        f"Vamos a aprobar a **{full_name}**.{warning}",
        f"Let's approve **{full_name}**.{warning}",
    )


def friendly_approve_success(
    locale: str,
    *,
    full_name: str,
    client_id: int,
    advisor_name: str | None = None,
) -> str:
    del advisor_name
    return t(
        locale,
        (
            f"✅ Cliente **{full_name}** (#{client_id}) aprobado.\n\n"
            "- Ya puede entrar al portal a cargar sus datos y documentos.\n"
            "- El asesor se asignará automáticamente cuando complete datos y documentos.\n"
            "- Se envió la bienvenida por email y WhatsApp.\n"
            "- La contraseña temporal aparece en el modal de confirmación."
        ),
        (
            f"✅ Client **{full_name}** (#{client_id}) approved.\n\n"
            "- They can now sign in to the portal to upload their data and documents.\n"
            "- An advisor will be assigned automatically once data and documents are complete.\n"
            "- Welcome email and WhatsApp were sent.\n"
            "- The temporary password is shown in the confirmation modal."
        ),
    )


def friendly_approve_need_advisor(locale: str) -> str:
    return t(
        locale,
        "Para continuar con la aprobación, indicame el **asesor** (nombre o email).",
        "To continue with the approval, tell me the **advisor** (name or email).",
    )


def friendly_reject_need_reason(locale: str) -> str:
    return t(
        locale,
        "Para rechazar al cliente, escribí el **motivo** (al menos 5 caracteres).",
        "To reject the client, write the **reason** (at least 5 characters).",
    )


def friendly_reject_one_intro(locale: str, *, full_name: str) -> str:
    return t(
        locale,
        f"Entendido. Para rechazar a **{full_name}**, contame el **motivo** (en una frase).",
        f"Understood. To reject **{full_name}**, tell me the **reason**.",
    )


def friendly_verify_pending_footer(locale: str) -> str:
    return t(
        locale,
        "\n\nSi querés, decime por ejemplo: *aprobar a [nombre]*, *aprobar todos*, *rechazar a [nombre]* o *rechazar todos*.",
        "\n\nYou can say: *approve [name]*, *approve all*, *reject [name]*, or *reject all*.",
    )


def friendly_upload_document_start(locale: str, *, for_staff: bool) -> str:
    if for_staff:
        return t(
            locale,
            "Perfecto, vamos a **subir un documento** para el cliente. Elegí el tipo abajo o decime cuál es (ej. licencia frente, SSN).",
            "Great, let's **upload a document** for the client. Pick the type below or tell me which one (e.g. license front, SSN).",
        )
    return t(
        locale,
        "Dale, vamos a **subir un documento**. Elegí el tipo abajo o decime cuál es (ej. licencia frente, SSN).",
        "Sure, let's **upload a document**. Pick the type below or tell me which one (e.g. license front, SSN).",
    )


def friendly_upload_document_need_client(locale: str) -> str:
    return t(
        locale,
        "¿Para qué **cliente** es el documento? Decime el **#ID** o el nombre.",
        "Which **client** is this document for? Tell me the **#ID** or name.",
    )


def friendly_upload_document_need_type(locale: str) -> str:
    return t(
        locale,
        "¿Qué **tipo de documento** querés subir? Elegí una opción abajo.",
        "Which **document type** do you want to upload? Pick an option below.",
    )


def friendly_upload_document_ready(locale: str, *, document_label: str) -> str:
    return t(
        locale,
        f"Listo, vamos con **{document_label}**. Tocá el clip 📎 y elegí el archivo (PDF o imagen).",
        f"Got it — **{document_label}**. Tap the clip 📎 and choose the file (PDF or image).",
    )


def friendly_upload_board_start(locale: str) -> str:
    return t(
        locale,
        "Vamos a **adjuntar un archivo a una tarjeta** del tablero. Elegí la tarjeta abajo o decime el título / #ID.",
        "Let's **attach a file to a board card**. Pick the card below or tell me the title / #ID.",
    )


def friendly_upload_board_need_client(locale: str) -> str:
    return t(
        locale,
        "¿De qué **cliente** es la tarjeta? Decime el **#ID** o el nombre.",
        "Which **client's** card is it? Tell me the **#ID** or name.",
    )


def friendly_upload_board_need_card(locale: str) -> str:
    return t(
        locale,
        "¿A qué **tarjeta** del tablero querés adjuntar el archivo?",
        "Which board **card** should receive the file?",
    )


def friendly_upload_board_ready(locale: str, *, card_title: str) -> str:
    return t(
        locale,
        f"Perfecto, tarjeta **{card_title}**. Tocá el clip 📎 y elegí el archivo.",
        f"Perfect — card **{card_title}**. Tap the clip 📎 and choose the file.",
    )
