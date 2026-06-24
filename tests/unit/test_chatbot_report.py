from app.services.chatbot.actions import CLIENT_REPORT_PATTERN, PENDING_APPROVAL_QUERY_PATTERN
from app.services.chatbot.approval_rules import validate_approval_requirements
from app.services.chatbot.report import format_client_report, format_pending_approval_answer


def test_pending_approval_query_pattern_matches_natural_questions():
    assert PENDING_APPROVAL_QUERY_PATTERN.search("tengo algun cliente pendiente de aprobacion")
    assert PENDING_APPROVAL_QUERY_PATTERN.search("hay clientes pendientes de revision")
    assert PENDING_APPROVAL_QUERY_PATTERN.search("cuantos clientes pendientes hay")


def test_client_report_pattern_matches():
    assert CLIENT_REPORT_PATTERN.search("informe completo del cliente")
    assert CLIENT_REPORT_PATTERN.search("dame un reporte de Juan")
    assert CLIENT_REPORT_PATTERN.search("quiero el estado completo de cliente 103")


def test_validate_approval_requirements_requires_source_and_merchant():
    from unittest.mock import MagicMock

    client = MagicMock()
    client.id = 1
    client.first_name = "Ana"
    client.last_name = "Lopez"
    client.email = "ana@example.com"
    client.phone = "+5491123456789"
    client.source = None
    client.merchant_id = None

    service = MagicMock()
    service.find_client_with_email = MagicMock(return_value=None)
    service.find_client_with_phone = MagicMock(return_value=None)

    issues = validate_approval_requirements(client, service)
    assert "Fuente sin definir" in issues
    assert "Comercio sin definir" in issues


def test_format_pending_approval_answer_distinguishes_ready_clients():
    reply = format_pending_approval_answer(
        "es",
        [
            {"id": 103, "nombre": "Angela Silva", "listo_para_aprobar": True, "problemas_aprobacion": []},
            {
                "id": 104,
                "nombre": "Juan Perez",
                "listo_para_aprobar": False,
                "problemas_aprobacion": ["Email vacío"],
            },
        ],
    )
    assert "Angela Silva" in reply
    assert "Listos para aprobar" in reply
    assert "después de la aprobación" in reply
    assert "Email vacío" in reply
    assert "SSN" not in reply


def test_format_client_report_includes_documents_and_board():
    detail = {
        "id": 103,
        "nombre": "Angela Silva",
        "email": "angela@example.com",
        "telefono": "+1234567890",
        "estado": "EN_CARGA_DATOS",
        "fuente": "WHATSAPP",
        "fuente_label": "WhatsApp",
        "comercio": "ePoint Lab",
        "aprobado": True,
        "problemas_aprobacion": [],
        "pendientes_onboarding": ["SSN", "Documento: Tarjeta SSN"],
        "documentos_requeridos": [
            {"tipo": "Tarjeta SSN", "subido": False, "estado_verificacion": "FALTANTE"},
            {
                "tipo": "Licencia de conducir (frente)",
                "subido": True,
                "estado_verificacion": "RECHAZADO",
                "motivos_rechazo": {"es": ["Imagen borrosa"], "en": ["Blurry image"]},
            },
        ],
        "documentos_adicionales": [],
        "tablero": {
            "existe": True,
            "resumen": {"total_tarjetas": 2, "completadas": 1, "pendientes": 1},
            "columnas": [
                {
                    "columna": "Pendiente",
                    "tarjetas": [{"titulo": "Crear cuenta", "estado": "PENDIENTE", "requiere_archivo": False, "requiere_credenciales": True}],
                }
            ],
        },
    }
    reply = format_client_report("es", detail)
    assert "Informe de **Angela Silva**" in reply
    assert "Tarjeta SSN" in reply
    assert "No subido" in reply
    assert "Imagen borrosa" in reply
    assert "Crear cuenta" in reply
    assert "POST-aprobación" in reply or "Pendientes de onboarding" in reply
