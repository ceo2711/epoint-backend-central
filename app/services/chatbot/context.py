import json
import re
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.models.address import Address
from app.models.client import Client
from app.models.document import Document
from app.models.enums import DocumentType, TaskStatus
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.boards import BoardService
from app.services.clients import ClientService
from app.services.documents import DocumentService

DOCUMENT_TYPE_LABELS = {
    DocumentType.SSN_CARD.value: "Tarjeta SSN",
    DocumentType.DRIVERS_LICENSE_FRONT.value: "Licencia de conducir (frente)",
    DocumentType.DRIVERS_LICENSE_BACK.value: "Licencia de conducir (dorso)",
    DocumentType.UTILITY_BILL.value: "Utility Bill (factura de servicios)",
    DocumentType.PASSPORT.value: "Pasaporte",
    DocumentType.GREEN_CARD.value: "Green Card",
    DocumentType.WORK_PERMIT.value: "Permiso de trabajo",
    DocumentType.BANK_STATEMENT.value: "Estado de cuenta bancario",
}

REQUIRED_DOCUMENT_TYPES = [
    DocumentType.SSN_CARD.value,
    DocumentType.DRIVERS_LICENSE_FRONT.value,
    DocumentType.DRIVERS_LICENSE_BACK.value,
    DocumentType.UTILITY_BILL.value,
]

STAFF_ROLES = {"ADMIN", "ONBOARDING_MANAGER", "ADVISOR", "AREA_LEADER"}
SALES_ROLE = "SALES_REP"
CLIENT_ROLE = "CLIENT"


class ChatbotContextBuilder:
    def __init__(self, db, user: User) -> None:
        self.db = db
        self.user = user
        self.clients = ClientService(db)
        self.documents = DocumentService(db)
        self.boards = BoardService(db)
        self.settings = get_settings()

    def _can_approve(self) -> bool:
        from app.api.deps import get_user_permissions

        perms = set(get_user_permissions(self.db, self.user))
        if self.user.role.code == "ADMIN":
            return True
        return "clients:approve" in perms

    def _can_create(self) -> bool:
        from app.api.deps import get_user_permissions

        perms = set(get_user_permissions(self.db, self.user))
        if self.user.role.code == "ADMIN":
            return True
        return "clients:create" in perms

    def resolve_client_id(self, message: str, client_id: int | None) -> int | None:
        if client_id is not None:
            return client_id if self.clients.user_can_access_client(self.user, client_id) else None

        role = self.user.role.code
        if role == CLIENT_ROLE:
            return self.user.client_id

        id_match = re.search(r"(?:cliente\s*)?#?(\d{1,8})\b", message, flags=re.IGNORECASE)
        if id_match:
            candidate = int(id_match.group(1))
            if self.clients.user_can_access_client(self.user, candidate):
                return candidate

        scoped_query = self.clients._scoped_clients_query(self.user)
        clients = self.db.execute(scoped_query.order_by(Client.created_at.desc()).limit(200)).scalars().all()
        lowered = message.lower()
        for client in clients:
            full_name = client.full_name.lower()
            if full_name and full_name in lowered:
                return client.id
            if client.email.lower() in lowered:
                return client.id
            first = client.first_name.lower()
            last = client.last_name.lower()
            if first and last and first in lowered and last in lowered:
                return client.id

        return None

    def build(self, *, message: str, client_id: int | None) -> tuple[str, int | None]:
        role = self.user.role.code
        resolved_client_id = self.resolve_client_id(message, client_id)

        if role == CLIENT_ROLE:
            payload = self._build_client_payload()
            return json.dumps(payload, ensure_ascii=False, indent=2), resolved_client_id

        if role == SALES_ROLE:
            payload = self._build_sales_payload(include_actions=self._can_create())
            return json.dumps(payload, ensure_ascii=False, indent=2), resolved_client_id

        if role in STAFF_ROLES:
            payload = self._build_staff_payload(resolved_client_id, include_approval_data=self._can_approve())
            return json.dumps(payload, ensure_ascii=False, indent=2), resolved_client_id

        payload = {"note": "Rol sin contexto específico configurado."}
        return json.dumps(payload, ensure_ascii=False, indent=2), resolved_client_id

    def _build_sales_payload(self, *, include_actions: bool) -> dict[str, Any]:
        clients = self.db.execute(
            self.clients._scoped_clients_query(self.user).order_by(Client.created_at.desc()).limit(100)
        ).scalars().all()

        approved: list[dict[str, Any]] = []
        not_approved: list[dict[str, Any]] = []

        for client in clients:
            item = {
                "id": client.id,
                "nombre": client.full_name,
                "email": client.email,
                "estado": client.status,
                "aprobado": client.approved_at is not None,
            }
            if client.approved_at is not None:
                approved.append(item)
            else:
                not_approved.append(item)

        payload: dict[str, Any] = {
            "rol": "SALES_REP",
            "alcance": "Solo clientes registrados por este vendedor.",
            "resumen": {
                "total": len(clients),
                "aprobados": len(approved),
                "no_aprobados": len(not_approved),
            },
            "clientes_aprobados": approved,
            "clientes_no_aprobados": not_approved,
        }
        if include_actions:
            payload["acciones_disponibles"] = [
                "registrar cliente (nombre, apellido, email, teléfono)",
            ]
        return payload

    def _build_staff_payload(self, client_id: int | None, *, include_approval_data: bool) -> dict[str, Any]:
        stats = self.clients.get_client_stats(self.user)
        clients = self.db.execute(
            self.clients._scoped_clients_query(self.user).order_by(Client.created_at.desc()).limit(80)
        ).scalars().all()

        complete_count = 0
        incomplete_clients: list[dict[str, Any]] = []
        client_summaries: list[dict[str, Any]] = []

        for client in clients:
            data_complete = self.clients.check_data_complete(client)
            if data_complete:
                complete_count += 1
            else:
                incomplete_clients.append(
                    {
                        "id": client.id,
                        "nombre": client.full_name,
                        "estado": client.status,
                        "faltantes": self._profile_gaps(client),
                    }
                )
            client_summaries.append(
                {
                    "id": client.id,
                    "nombre": client.full_name,
                    "email": client.email,
                    "estado": client.status,
                    "aprobado": client.approved_at is not None,
                    "datos_completos": data_complete,
                }
            )

        payload: dict[str, Any] = {
            "rol": self.user.role.code,
            "estadisticas_generales": stats,
            "resumen_datos": {
                "clientes_con_datos_completos": complete_count,
                "clientes_con_datos_incompletos": len(clients) - complete_count,
            },
            "clientes_datos_incompletos": incomplete_clients[:30],
            "clientes": client_summaries,
        }

        if client_id is not None and self.clients.user_can_access_client(self.user, client_id):
            payload["cliente_consultado"] = self._client_detail_payload(client_id)

        if include_approval_data:
            from app.services.chatbot.actions import ChatbotActionHandler

            handler = ChatbotActionHandler(self.db, self.user)
            pending = handler._pending_clients()
            payload["clientes_pendientes_revision"] = [
                {
                    "id": client.id,
                    "nombre": client.full_name,
                    "email": client.email,
                    "telefono": client.phone,
                    "datos_ok": len(problems) == 0,
                    "problemas": problems,
                }
                for client in pending
                for problems in [handler.validate_registration_data(client)]
            ]
            payload["acciones_disponibles"] = [
                "verificar pendientes",
                "aprobar cliente #ID",
                "aprobar todos",
                "rechazar cliente #ID",
                "rechazar todos",
            ]

        return payload

    def _build_client_payload(self) -> dict[str, Any]:
        client_id = self.user.client_id
        if not client_id:
            return {"error": "Usuario cliente sin client_id asociado."}
        return {
            "rol": "CLIENT",
            "portal": {
                "datos_url": f"{self.settings.portal_base_url}/portal/datos",
                "documentos_url": f"{self.settings.portal_base_url}/portal/documentos",
                "tablero_url": f"{self.settings.portal_base_url}/portal/tablero",
            },
            "cliente": self._client_detail_payload(client_id),
        }

    def _client_detail_payload(self, client_id: int) -> dict[str, Any]:
        client = self.clients.get_client_detail(client_id)
        if client is None:
            return {"error": f"Cliente {client_id} no encontrado."}

        uploaded_docs = {doc.type: doc for doc in client.documents}
        documents_info: list[dict[str, Any]] = []

        for doc_type in REQUIRED_DOCUMENT_TYPES:
            doc = uploaded_docs.get(doc_type)
            if doc is None:
                documents_info.append(
                    {
                        "tipo": DOCUMENT_TYPE_LABELS.get(doc_type, doc_type),
                        "subido": False,
                        "estado_verificacion": "FALTANTE",
                    }
                )
                continue

            brief = self.documents.to_brief(doc, include_download_url=False)
            documents_info.append(
                {
                    "tipo": DOCUMENT_TYPE_LABELS.get(doc_type, doc_type),
                    "subido": True,
                    "estado_verificacion": brief.verification_status,
                    "motivos_rechazo": brief.rejection_reasons.model_dump() if brief.rejection_reasons else None,
                    "motivos_aprobacion": brief.approval_reasons.model_dump() if brief.approval_reasons else None,
                }
            )

        extra_docs = [
            {
                "tipo": DOCUMENT_TYPE_LABELS.get(doc.type, doc.type),
                "estado_verificacion": doc.verification_status,
            }
            for doc in client.documents
            if doc.type not in REQUIRED_DOCUMENT_TYPES
        ]

        board_summary = self._board_summary(client_id)

        return {
            "id": client.id,
            "nombre": client.full_name,
            "email": client.email,
            "telefono": client.phone,
            "estado": client.status,
            "aprobado": client.approved_at is not None,
            "motivo_rechazo": client.rejection_reason,
            "datos_completos": self.clients.check_data_complete(client),
            "faltantes_perfil": self._profile_gaps(client),
            "documentos_requeridos": documents_info,
            "documentos_adicionales": extra_docs,
            "tablero": board_summary,
        }

    def _profile_gaps(self, client: Client) -> list[str]:
        gaps: list[str] = []
        if not client.ssn_encrypted:
            gaps.append("SSN")
        if not client.date_of_birth:
            gaps.append("Fecha de nacimiento")

        current_addr = self.db.execute(
            select(Address).where(Address.client_id == client.id, Address.type == "CURRENT")
        ).scalar_one_or_none()
        if not current_addr:
            gaps.append("Dirección actual")

        vehicle = self.db.execute(
            select(Vehicle).where(Vehicle.client_id == client.id, Vehicle.order == 1)
        ).scalar_one_or_none()
        if not vehicle:
            gaps.append("Vehículo principal")

        uploaded_types = {
            doc.type
            for doc in self.db.execute(select(Document).where(Document.client_id == client.id)).scalars().all()
        }
        for doc_type in REQUIRED_DOCUMENT_TYPES:
            if doc_type not in uploaded_types:
                gaps.append(f"Documento: {DOCUMENT_TYPE_LABELS.get(doc_type, doc_type)}")

        return gaps

    def _board_summary(self, client_id: int) -> dict[str, Any] | None:
        board = self.boards.get_board_for_client(client_id)
        if board is None:
            return {"existe": False, "mensaje": "El cliente aún no tiene tablero de onboarding."}

        columns: list[dict[str, Any]] = []
        total_cards = 0
        completed_cards = 0
        pending_cards = 0

        for board_list in sorted(board.lists, key=lambda item: item.position):
            cards_info: list[dict[str, Any]] = []
            for card in sorted(board_list.cards, key=lambda item: item.position):
                total_cards += 1
                if card.status == TaskStatus.COMPLETADA.value:
                    completed_cards += 1
                else:
                    pending_cards += 1
                cards_info.append(
                    {
                        "titulo": card.title,
                        "estado": card.status,
                        "requiere_archivo": card.requires_file_upload,
                        "requiere_credenciales": card.requires_credentials,
                        "instrucciones_resumen": (card.instructions_md or "")[:280],
                    }
                )
            columns.append(
                {
                    "columna": board_list.title,
                    "tarjetas": cards_info,
                }
            )

        return {
            "existe": True,
            "resumen": {
                "total_tarjetas": total_cards,
                "completadas": completed_cards,
                "pendientes": pending_cards,
            },
            "columnas": columns,
        }
