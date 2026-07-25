"""Guías tutoriales de la plataforma para el chatbot.

Inyecta en el contexto del LLM un mapa de pantallas (con URLs) y guías cortas
"cómo hago X", filtradas por rol. Sin RAG: el corpus es chico y vive acá.
"""

from __future__ import annotations

import re
from typing import Any

# Roles internos de staff (misma convención que context.py).
STAFF_ROLES = frozenset({"ADMIN", "BRANCH_MANAGER", "ONBOARDING_MANAGER", "ADVISOR", "AREA_LEADER"})
SALES_ROLE = "SALES_REP"
CLIENT_ROLE = "CLIENT"

HOW_TO_PATTERN = re.compile(
    r"\b("
    r"c[oó]mo|como|d[oó]nde|donde|para\s+qu[eé]|qu[eé]\s+es|qu[eé]\s+hago|"
    r"tutorial|gu[ií]a|ayuda|explicame|explicá|explica|"
    r"no\s+s[eé]|no\s+entiendo|me\s+perd[ií]|"
    r"how|where|what\s+is|tutorial|guide|help|explain"
    r")\b",
    re.IGNORECASE,
)


def _url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}{path}"


def platform_sections_for_role(role: str, base_url: str) -> list[dict[str, str]]:
    """Mapa de pantallas visibles según el rol (espejo aproximado de la nav)."""
    base = base_url.rstrip("/")

    if role == CLIENT_ROLE:
        return [
            {
                "nombre": "Mi portal",
                "url": _url(base, "/portal"),
                "para_que": "Resumen de bienvenida y acceso rápido a las demás secciones.",
            },
            {
                "nombre": "Mis datos",
                "url": _url(base, "/portal/datos"),
                "para_que": "Completar SSN, fecha de nacimiento, dirección y vehículo.",
            },
            {
                "nombre": "Documentos",
                "url": _url(base, "/portal/documentos"),
                "para_que": "Subir tarjeta SSN, identidad y comprobante de domicilio.",
            },
            {
                "nombre": "Tablero",
                "url": _url(base, "/portal/tablero"),
                "para_que": "Avanzar tareas de onboarding (Client TO DO) con adjuntos cuando corresponda.",
            },
        ]

    sections: list[dict[str, str]] = [
        {
            "nombre": "Panel",
            "url": _url(base, "/dashboard"),
            "para_que": "Métricas y resumen del estado de clientes / prospectos según tu rol.",
        },
        {
            "nombre": "Clientes",
            "url": _url(base, "/clientes"),
            "para_que": "Listado y detalle de clientes: estado, datos, documentos, tablero y acceso al portal.",
        },
    ]

    if role in {SALES_ROLE, "ADMIN", "BRANCH_MANAGER", "AREA_LEADER"}:
        sections.extend(
            [
                {
                    "nombre": "Prospectos",
                    "url": _url(base, "/prospectos"),
                    "para_que": "Leads del embudo comercial antes de convertirse en clientes.",
                },
                {
                    "nombre": "Calendario",
                    "url": _url(base, "/calendario"),
                    "para_que": "Reuniones de Calendly: conectar cuenta, ver agenda y vincular prospectos.",
                },
                {
                    "nombre": "Contratos",
                    "url": _url(base, "/contratos"),
                    "para_que": "Envío y seguimiento de contratos DocuSign.",
                },
                {
                    "nombre": "Pagos",
                    "url": _url(base, "/pagos"),
                    "para_que": "Generar y compartir links de pago (Authorize.net / PayPal).",
                },
            ]
        )

    if role in {"ADMIN", "BRANCH_MANAGER", "ONBOARDING_MANAGER", "ADVISOR", "AREA_LEADER"}:
        # Usuarios visibles para quien gestiona el equipo / onboarding.
        if role in {"ADMIN", "BRANCH_MANAGER"}:
            sections.append(
                {
                    "nombre": "Usuarios",
                    "url": _url(base, "/usuarios"),
                    "para_que": "Alta y gestión de usuarios internos de la sucursal / empresa.",
                }
            )

    if role == "ADMIN":
        sections.extend(
            [
                {
                    "nombre": "Sedes",
                    "url": _url(base, "/sedes"),
                    "para_que": "Sucursales de la empresa.",
                },
                {
                    "nombre": "Comercios",
                    "url": _url(base, "/comercios"),
                    "para_que": "Comercios / merchants asociados a la operación.",
                },
                {
                    "nombre": "Fuentes",
                    "url": _url(base, "/fuentes"),
                    "para_que": "Catálogo de fuentes de captación de clientes.",
                },
                {
                    "nombre": "Roles",
                    "url": _url(base, "/roles"),
                    "para_que": "Roles y permisos de la plataforma.",
                },
            ]
        )

    sections.append(
        {
            "nombre": "Mi cuenta",
            "url": _url(base, "/cuenta"),
            "para_que": "Perfil, avatar, contraseña y doble factor de autenticación.",
        }
    )
    return sections


# Guías estáticas. `roles`: None = todos los roles internos (no cliente).
# `keywords`: ayudan a priorizar la guía cuando el mensaje del usuario las menciona.
GUIDES: list[dict[str, Any]] = [
    {
        "id": "flujo_general",
        "titulo": "Flujo general de la plataforma",
        "roles": None,
        "keywords": ("flujo", "plataforma", "cómo funciona", "como funciona", "overview", "how it works"),
        "pasos": [
            "Ventas registra un prospecto o cliente (o convierte un prospecto tras pago/contrato).",
            "Onboarding revisa y aprueba al cliente (solo datos básicos: nombre, email, teléfono, fuente, comercio).",
            "El cliente entra al portal, completa datos y sube documentos.",
            "Cuando datos + documentos están listos, el cliente pasa a «Listo para trabajar» y se asigna asesor + tablero.",
            "El asesor acompaña las tareas del tablero hasta completar el onboarding.",
        ],
    },
    {
        "id": "registrar_cliente",
        "titulo": "Cómo registrar un cliente",
        "roles": {SALES_ROLE, "ADMIN", "BRANCH_MANAGER", "AREA_LEADER", "ONBOARDING_MANAGER"},
        "keywords": ("registrar", "registro", "nuevo cliente", "alta", "register"),
        "pasos": [
            "Desde el chat: pedí registrar un cliente y completá nombre, email, teléfono, fuente y comercio.",
            "También podés hacerlo desde Clientes → Agregar cliente.",
            "Si venís de un prospecto, usá la conversión desde el detalle del prospecto o tras un pago.",
            "Podés registrar varios seguidos en el chat o pegar bloques estructurados en un solo mensaje.",
        ],
        "urls": ["/clientes"],
    },
    {
        "id": "aprobar_cliente",
        "titulo": "Cómo aprobar o rechazar un cliente",
        "roles": {"ADMIN", "BRANCH_MANAGER", "ONBOARDING_MANAGER"},
        "keywords": ("aprobar", "rechazar", "pendiente", "revisión", "revision", "approve", "reject"),
        "pasos": [
            "Andá a Clientes y filtrá por estado «Pendiente de revisión».",
            "Para aprobar solo se necesitan: nombre completo, email, teléfono, fuente y comercio.",
            "Documentos y datos del portal NO bloquean la aprobación inicial.",
            "Desde el chat podés decir: «aprobar a Juan», «aprobar todos», «rechazar a #123 porque…».",
            "El asesor se asigna automáticamente más adelante, cuando el cliente completa datos y documentos (salvo que onboarding lo asigne antes a mano).",
        ],
        "urls": ["/clientes"],
    },
    {
        "id": "portal_cliente",
        "titulo": "Qué hace el cliente en el portal",
        "roles": None,
        "keywords": ("portal", "datos", "documentos", "tablero", "onboarding del cliente"),
        "pasos": [
            "Tras la aprobación, el cliente recibe acceso al portal (email + contraseña temporal).",
            "En Mis datos completa SSN, fecha de nacimiento, dirección (con autocompletado) y vehículo.",
            "En Documentos sube SSN, identidad y comprobante de domicilio.",
            "En Tablero avanza las tareas Client TO DO (con adjuntos si la tarjeta lo pide).",
            "Podés ver el progreso y regenerar la contraseña del portal desde el detalle del cliente.",
        ],
        "urls": ["/clientes"],
    },
    {
        "id": "subir_documentos",
        "titulo": "Cómo subir documentos o archivos al tablero",
        "roles": None,
        "keywords": ("documento", "documentos", "subir", "adjunt", "clip", "upload", "tablero"),
        "pasos": [
            "Usá el clip 📎 del chat: elegí si es documento del cliente o adjunto de una tarjeta del tablero.",
            "También podés subirlos desde el detalle del cliente (Documentos / Tablero) o desde el portal del cliente.",
            "Los documentos pasan por verificación automática con IA; el estado aparece en el detalle.",
        ],
    },
    {
        "id": "informe_cliente",
        "titulo": "Cómo pedir un informe de un cliente",
        "roles": None,
        "keywords": ("informe", "reporte", "report", "resumen del cliente"),
        "pasos": [
            "En el chat pedí «informe de [nombre / email / #ID]».",
            "El sistema arma un resumen con datos, documentos (estado y motivos) y tablero.",
            "Solo ves clientes a los que tu rol tiene acceso.",
        ],
    },
    {
        "id": "prospectos",
        "titulo": "Cómo trabajar con prospectos",
        "roles": {SALES_ROLE, "ADMIN", "BRANCH_MANAGER", "AREA_LEADER"},
        "keywords": ("prospecto", "prospectos", "lead", "embudo", "pipeline"),
        "pasos": [
            "Andá a Prospectos para crear y mover leads por el embudo.",
            "Podés calificar el lead, vincular reuniones de Calendly y generar links de pago.",
            "Cuando corresponde, convertís el prospecto a cliente (queda pendiente de revisión de onboarding).",
        ],
        "urls": ["/prospectos"],
    },
    {
        "id": "calendario",
        "titulo": "Cómo usar el calendario (Calendly)",
        "roles": {SALES_ROLE, "ADMIN", "BRANCH_MANAGER", "AREA_LEADER"},
        "keywords": ("calendario", "calendly", "reunión", "reunion", "agendar", "meeting"),
        "pasos": [
            "Andá a Calendario y conectá tu Personal Access Token de Calendly.",
            "Desde ahí ves reuniones, enlace público y vinculación con prospectos.",
            "En el chat podés pedir «mis reuniones de hoy/semana» y, si está habilitado, agendar/cancelar/reprogramar.",
        ],
        "urls": ["/calendario"],
    },
    {
        "id": "pagos",
        "titulo": "Cómo generar un link de pago",
        "roles": {SALES_ROLE, "ADMIN", "BRANCH_MANAGER", "AREA_LEADER"},
        "keywords": ("pago", "pagos", "link de pago", "paypal", "authorize"),
        "pasos": [
            "Andá a Pagos → Nuevo link de pago.",
            "Completá datos del cliente, monto y proveedor; opcionalmente vinculá un prospecto y enviá el email.",
            "El link se copia al portapapeles para compartirlo.",
        ],
        "urls": ["/pagos"],
    },
    {
        "id": "asesores",
        "titulo": "Cómo trabajar como asesor",
        "roles": {"ADVISOR", "ADMIN", "BRANCH_MANAGER", "AREA_LEADER", "ONBOARDING_MANAGER"},
        "keywords": ("asesor", "asesores", "asignar asesor", "listo para trabajar"),
        "pasos": [
            "Los asesores ven los clientes asignados en Clientes.",
            "Desde el detalle revisás datos, documentos y el tablero de onboarding.",
            "Onboarding (o la autoasignación al pasar a «Listo para trabajar») puede asignar uno o más asesores.",
            "Podés agregar o quitar asesores desde el panel del detalle del cliente (según estado).",
        ],
        "urls": ["/clientes"],
    },
    {
        "id": "cuenta_seguridad",
        "titulo": "Mi cuenta y seguridad",
        "roles": None,
        "keywords": ("cuenta", "contraseña", "password", "2fa", "doble factor", "avatar"),
        "pasos": [
            "Andá a Mi cuenta para actualizar avatar y contraseña.",
            "El doble factor (2FA) es obligatorio para usuarios internos.",
            "Si perdés acceso al autenticador, pedile ayuda a un administrador.",
        ],
        "urls": ["/cuenta"],
    },
]


def _guide_visible_to_role(guide: dict[str, Any], role: str) -> bool:
    roles = guide.get("roles")
    if role == CLIENT_ROLE:
        # El cliente ya tiene su propio prompt de portal; estas guías son internas.
        return False
    if roles is None:
        return True
    return role in roles


def _score_guide(guide: dict[str, Any], message_lower: str) -> int:
    score = 0
    for kw in guide.get("keywords") or ():
        if kw.lower() in message_lower:
            score += 2 if len(kw) > 4 else 1
    return score


def select_guides(role: str, message: str, *, limit: int = 4) -> list[dict[str, Any]]:
    """Elige guías relevantes. Si el mensaje parece una duda, prioriza por keywords."""
    visible = [g for g in GUIDES if _guide_visible_to_role(g, role)]
    if not visible:
        return []

    message_lower = (message or "").lower()
    how_to = bool(HOW_TO_PATTERN.search(message_lower))
    scored = [( _score_guide(g, message_lower), g) for g in visible]
    scored.sort(key=lambda item: item[0], reverse=True)

    if how_to or any(score > 0 for score, _ in scored):
        picked = [g for score, g in scored if score > 0][:limit]
        if picked:
            return [_serialize_guide(g) for g in picked]
        # Duda genérica: devolver las guías base del rol.
        defaults = ["flujo_general", "registrar_cliente", "aprobar_cliente", "portal_cliente"]
        by_id = {g["id"]: g for g in visible}
        result = [by_id[i] for i in defaults if i in by_id][:limit]
        if result:
            return [_serialize_guide(g) for g in result]

    # Fuera de modo guía: igual dejamos 2 guías cortas de referencia en el contexto.
    defaults = ["flujo_general", "portal_cliente"]
    by_id = {g["id"]: g for g in visible}
    return [_serialize_guide(by_id[i]) for i in defaults if i in by_id][:2]


def _serialize_guide(guide: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": guide["id"],
        "titulo": guide["titulo"],
        "pasos": list(guide["pasos"]),
    }


def build_platform_guide_context(
    *,
    role: str,
    base_url: str,
    message: str,
) -> dict[str, Any]:
    """Bloque `plataforma` para inyectar en el JSON de contexto del chatbot."""
    sections = platform_sections_for_role(role, base_url)
    guides = select_guides(role, message)
    # Resolver URLs absolutas en las guías seleccionadas (si las tenían relativas).
    guide_by_id = {g["id"]: g for g in GUIDES}
    enriched: list[dict[str, Any]] = []
    for item in guides:
        full = dict(item)
        raw = guide_by_id.get(item["id"]) or {}
        paths = raw.get("urls") or []
        if paths:
            full["urls"] = [_url(base_url, path) for path in paths]
        enriched.append(full)

    return {
        "secciones": sections,
        "guias_tutoriales": enriched,
        "nota_guia": (
            "Si el usuario pregunta cómo usar la plataforma, dónde encontrar algo o qué hacer, "
            "respondé con pasos claros y enlaces de `plataforma.secciones` / `plataforma.guias_tutoriales`. "
            "No inventes pantallas que no estén en el mapa."
        ),
    }


def is_how_to_question(message: str) -> bool:
    return bool(HOW_TO_PATTERN.search(message or ""))
