"""QA E2E — Flujo completo del cliente (prospecto → cliente listo para trabajar).

Simula el flujo real usando los servicios del backend (misma lógica que la API):
  1.  Vendedor crea prospecto                      → PENDIENTE_CONTACTAR
  2.  Reunión Calendly vinculada + concretada      → LEAD_CONTACTADO
  3.  Contrato DocuSign enviado                    → CONTRATO_ENVIADO
  4.  Contrato firmado (webhook DocuSign simulado)
  5.  Pago completado (webhook de pago simulado)   → PAGO_COMPLETADO + conversión a cliente
  6.  Aprobación en onboarding                     → EN_CARGA_DATOS + usuario del portal
  7.  Cliente carga datos (SSN, nacimiento, dirección, vehículo)
  8.  Cliente sube documentos                      → DOCUMENTOS_EN_REVISION
  9.  Verificación IA aprueba documentos           → LISTO_PARA_TRABAJAR
  10. Se asigna asesor automáticamente y se crea el tablero

Los eventos externos (Calendly, DocuSign, webhook de pago, storage S3 y el
worker de verificación IA) se simulan al nivel exacto en el que esos sistemas
tocan la base, llamando después a los mismos hooks que usa la app real
(`on_envelope_completed`, `on_payment_completed`, `sync_client_onboarding_status`).

Todos los datos creados quedan marcados como QA y se eliminan al final.
"""

import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Evitar envíos reales de email/WhatsApp durante el QA (la base es la de Heroku).
os.environ["NOTIFICATIONS_DRY_RUN"] = "true"

from datetime import date, datetime, timedelta, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.encryption import decrypt_value  # noqa: E402
from app.models.address import Address  # noqa: E402
from app.models.calendly_event import CalendlyEvent  # noqa: E402
from app.models.client import Client  # noqa: E402
from app.models.client_assignment import ClientAssignment  # noqa: E402
from app.models.docusign_envelope import DocusignEnvelope  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.enums import ClientStatus, DocumentVerificationStatus, ProspectStatus  # noqa: E402
from app.models.notification import Notification  # noqa: E402
from app.models.payment_link import PaymentLink, PaymentLinkStatus  # noqa: E402
from app.models.prospect import Prospect  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.vehicle import Vehicle  # noqa: E402
from app.services.client_onboarding_status import sync_client_onboarding_status  # noqa: E402
from app.services.clients import ClientService  # noqa: E402
from app.services.merchant_context import MerchantContextService  # noqa: E402
from app.services.prospects import ProspectService  # noqa: E402

SUFFIX = str(int(time.time()))[-7:]
QA_EMAIL = f"qa.flujo.{SUFFIX}@example.com"
QA_PHONE = f"+1305{SUFFIX}"
QA_LAST_NAME = f"Flujo{SUFFIX}"

RESULTS: list[tuple[str, bool, str]] = []


def check(step: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((step, ok, detail))
    mark = "[OK]  " if ok else "[FAIL]"
    print(f"  {mark} {step}" + (f" — {detail}" if detail else ""))
    return ok


def get_user(db, email: str) -> User | None:
    return db.execute(select(User).where(User.email == email)).scalar_one_or_none()


def run_flow(db, ids: dict) -> None:
    now = datetime.now(timezone.utc)

    # ── Paso 0: actores y precondiciones ─────────────────────────────
    print("\nPASO 0 — Actores y precondiciones")
    vendedor = get_user(db, "vendedor@epoint.com")
    onboarding = get_user(db, "onboarding@epoint.com")
    admin = get_user(db, "admin@epoint.com")
    check("Vendedor existe y activo", bool(vendedor and vendedor.is_active))
    check("Usuario onboarding existe y activo", bool(onboarding and onboarding.is_active))
    check("Admin existe", bool(admin))
    if not (vendedor and onboarding and admin):
        raise RuntimeError("Faltan usuarios base; no se puede continuar")

    advisors = (
        db.execute(
            select(User).join(Role).where(Role.code == "ADVISOR", User.is_active.is_(True))
        )
        .scalars()
        .all()
    )
    check("Hay asesores activos para auto-asignación", len(advisors) > 0, f"{len(advisors)} asesores")

    merchants = MerchantContextService(db).list_accessible_merchants(vendedor)
    check("Vendedor tiene comercio accesible", len(merchants) > 0)
    merchant = merchants[0]

    psvc = ProspectService(db)
    csvc = ClientService(db)

    # ── Paso 1: alta de prospecto ────────────────────────────────────
    print("\nPASO 1 — Vendedor registra al prospecto")
    prospect = psvc.create_prospect(
        actor=vendedor,
        first_name="QA",
        last_name=QA_LAST_NAME,
        email=QA_EMAIL,
        phone=QA_PHONE,
        merchant_id=merchant.id,
        notes="Prospecto de prueba QA — borrar",
    )
    ids["prospect"] = prospect.id
    check(
        "Prospecto creado en estado PENDIENTE_CONTACTAR",
        prospect.status == ProspectStatus.PENDIENTE_CONTACTAR.value,
        f"id={prospect.id}, status={prospect.status}",
    )
    check("Prospecto asignado al vendedor", prospect.assigned_to_user_id == vendedor.id)
    check("Prospecto hereda la sede del vendedor", prospect.sede_id == vendedor.sede_id,
          f"sede={prospect.sede_id}")

    # ── Paso 2: reunión Calendly ─────────────────────────────────────
    print("\nPASO 2 — Reunión con el vendedor (Calendly)")
    event = CalendlyEvent(
        user_id=vendedor.id,
        calendly_event_uri=f"qa://calendly/{SUFFIX}",
        name="Reunión QA",
        status="active",
        start_time=now - timedelta(hours=2),
        end_time=now - timedelta(hours=1, minutes=30),
        invitee_name=f"QA {QA_LAST_NAME}",
        invitee_email=QA_EMAIL,
    )
    db.add(event)
    db.commit()
    ids["calendly_event"] = event.id

    prospect = psvc.link_calendly_event(actor=vendedor, prospect=prospect, calendly_event_id=event.id)
    check("Reunión vinculada al prospecto", prospect.calendly_event_id == event.id)

    prospect = psvc.mark_contacted(actor=vendedor, prospect=prospect, note="Reunión concretada (QA)")
    check(
        "Reunión concretada → LEAD_CONTACTADO",
        prospect.status == ProspectStatus.LEAD_CONTACTADO.value,
        f"status={prospect.status}",
    )

    # ── Paso 3: contrato DocuSign ────────────────────────────────────
    print("\nPASO 3 — Contrato DocuSign (envío y firma)")
    envelope = DocusignEnvelope(
        docusign_envelope_id=f"qa-envelope-{SUFFIX}",
        sent_by_user_id=vendedor.id,
        merchant_id=merchant.id,
        signer_name=f"QA {QA_LAST_NAME}",
        signer_email=QA_EMAIL,
        template_id="qa-template",
        template_role_name="Client",
        subject="Contrato de servicio (QA)",
        status="sent",
    )
    db.add(envelope)
    db.commit()
    ids["envelope"] = envelope.id

    prospect = psvc.link_envelope(actor=vendedor, prospect=prospect, envelope_id=envelope.id)
    check(
        "Contrato enviado → CONTRATO_ENVIADO",
        prospect.status == ProspectStatus.CONTRATO_ENVIADO.value,
        f"status={prospect.status}",
    )

    # Guard: no se puede convertir sin pago
    try:
        psvc.convert_to_client(prospect=prospect, actor=vendedor)
        check("Bloqueo de conversión sin pago", False, "convirtió sin pago (no debería)")
    except HTTPException as exc:
        check("Bloqueo de conversión sin pago", exc.status_code == 400, f"HTTP {exc.status_code}")

    # Firma (webhook DocuSign simulado)
    envelope.status = "completed"
    envelope.completed_at = now
    db.flush()
    psvc.on_envelope_completed(envelope)
    db.commit()
    db.refresh(prospect)
    check(
        "Contrato firmado registrado, sin conversión todavía (falta pago)",
        prospect.converted_client_id is None,
    )

    # ── Paso 4: pago ─────────────────────────────────────────────────
    print("\nPASO 4 — Link de pago y pago completado")
    link = PaymentLink(
        created_by_user_id=vendedor.id,
        merchant_id=merchant.id,
        customer_first_name="QA",
        customer_last_name=QA_LAST_NAME,
        customer_email=QA_EMAIL,
        customer_phone=QA_PHONE,
        amount=Decimal("1500.00"),
        currency="USD",
        provider="stripe",
        payment_url=f"https://qa.local/pay/{SUFFIX}",
        description="Pago QA — borrar",
    )
    db.add(link)
    db.commit()
    ids["payment_link"] = link.id

    prospect = psvc.link_payment_link(actor=vendedor, prospect=prospect, payment_link_id=link.id)
    check("Link de pago vinculado al prospecto", prospect.payment_link_id == link.id)

    # Webhook de pago simulado
    link.status = PaymentLinkStatus.PAID.value
    link.paid_at = now
    db.flush()
    psvc.on_payment_completed(link)
    db.commit()
    db.refresh(prospect)

    check(
        "Pago completado → PAGO_COMPLETADO",
        prospect.status == ProspectStatus.PAGO_COMPLETADO.value,
        f"status={prospect.status}",
    )
    check("Conversión automática a cliente", prospect.converted_client_id is not None,
          f"client_id={prospect.converted_client_id}")
    if prospect.converted_client_id is None:
        raise RuntimeError("El prospecto no se convirtió; no se puede continuar")

    client = db.get(Client, prospect.converted_client_id)
    ids["client"] = client.id
    check("Contrato firmado quedó vinculado al cliente",
          client.docusign_envelope_id == envelope.id and client.docusign_contract_signed_at is not None)
    check("Pago quedó vinculado al cliente", link.client_id == client.id)
    check("Cliente mantiene la sede del prospecto", client.sede_id == prospect.sede_id)
    print(f"        Estado inicial del cliente: {client.status}")

    # ── Paso 5: aprobación en onboarding ─────────────────────────────
    print("\nPASO 5 — Aprobación en onboarding")
    auto_approved = client.status != ClientStatus.PENDIENTE_DE_REVISION.value
    if auto_approved:
        check("Cliente auto-aprobado al convertirse", True, f"status={client.status}")
    else:
        client, _msg = csvc.approve_client(actor=onboarding, client=client)
    check(
        "Cliente aprobado → EN_CARGA_DATOS",
        client.status == ClientStatus.EN_CARGA_DATOS.value,
        f"status={client.status}",
    )
    check("Aprobación registrada", client.approved_at is not None)

    portal_user = db.execute(
        select(User).join(Role).where(User.client_id == client.id, Role.code == "CLIENT")
    ).scalar_one_or_none()
    ids["portal_user"] = portal_user.id if portal_user else None
    check("Usuario del portal creado", portal_user is not None,
          f"email={portal_user.email if portal_user else '-'}")
    temp_ok = False
    if client.portal_temp_password_encrypted:
        try:
            temp_ok = len(decrypt_value(client.portal_temp_password_encrypted)) >= 8
        except Exception:
            temp_ok = False
    check("Contraseña temporal generada y desencriptable", temp_ok)

    # ── Paso 6: cliente carga sus datos en el portal ─────────────────
    print("\nPASO 6 — Cliente carga datos (portal)")
    actor_portal = portal_user or onboarding
    csvc.update_profile(actor=actor_portal, client=client, ssn="123456789",
                        date_of_birth=date(1990, 5, 20))
    check("SSN y fecha de nacimiento guardados",
          client.ssn_encrypted is not None and client.date_of_birth == date(1990, 5, 20))

    db.add(Address(client_id=client.id, type="CURRENT", street="123 QA Test St",
                   city="Miami", state="FL", zip_code="33101",
                   residence_since_month=1, residence_since_year=2020))
    db.add(Vehicle(client_id=client.id, order=1, model="Toyota Corolla", year=2021, color="Negro"))
    db.commit()
    check("Dirección actual y vehículo cargados", True)
    check("Datos aún incompletos sin documentos", not csvc.check_data_complete(client))

    # ── Paso 7: carga de documentos ──────────────────────────────────
    print("\nPASO 7 — Cliente sube documentos")
    doc_types = ["SSN_CARD", "DRIVERS_LICENSE_FRONT", "DRIVERS_LICENSE_BACK", "UTILITY_BILL"]
    status_before_last = None
    for i, doc_type in enumerate(doc_types):
        doc = Document(
            client_id=client.id,
            type=doc_type,
            storage_key=f"qa/{client.id}/{doc_type.lower()}.jpg",
            original_filename=f"{doc_type.lower()}.jpg",
            mime_type="image/jpeg",
            verification_status=DocumentVerificationStatus.EN_PROCESO.value,
        )
        db.add(doc)
        db.flush()
        if i == len(doc_types) - 1:
            status_before_last = client.status
        # Misma lógica que DocumentService.confirm_upload (sin storage real)
        if client.status == ClientStatus.EN_CARGA_DATOS.value and csvc.check_data_complete(client):
            client.status = ClientStatus.DOCUMENTOS_EN_REVISION.value
            csvc.on_documents_complete(client=client)
        db.commit()

    check("Con documentos parciales seguía EN_CARGA_DATOS",
          status_before_last == ClientStatus.EN_CARGA_DATOS.value)
    check(
        "Documentos completos → DOCUMENTOS_EN_REVISION",
        client.status == ClientStatus.DOCUMENTOS_EN_REVISION.value,
        f"status={client.status}",
    )

    # ── Paso 8a: un documento aprobado pero próximo a vencer ─────────
    print("\nPASO 8a — Documento aprobado pero próximo a vencer (debe frenar y avisar)")
    from app.services.onboarding_completeness import analyze_onboarding_gaps

    docs = db.execute(select(Document).where(Document.client_id == client.id)).scalars().all()
    for doc in docs:
        doc.verification_status = (
            DocumentVerificationStatus.PROXIMO_A_VENCER.value
            if doc.type == "DRIVERS_LICENSE_FRONT"
            else DocumentVerificationStatus.APROBADO.value
        )
    db.flush()
    sync_client_onboarding_status(db, client)
    db.commit()
    db.refresh(client)

    check(
        "Documento por vencer frena el pase a LISTO_PARA_TRABAJAR",
        client.status == ClientStatus.DOCUMENTOS_EN_REVISION.value,
        f"status={client.status}",
    )
    gaps = analyze_onboarding_gaps(db, client)
    check(
        "El cliente ve el documento por vencer en sus pendientes",
        gaps.needs_reminder and any("vence pronto" in item for item in gaps.all_pending_labels()),
        "; ".join(gaps.all_pending_labels()) or "sin pendientes",
    )
    check("Todavía sin asesor ni tablero", client.board is None)

    # ── Paso 8b: el cliente sube un documento vigente ────────────────
    print("\nPASO 8b — El cliente sube un documento vigente")
    for doc in docs:
        doc.verification_status = DocumentVerificationStatus.APROBADO.value
    db.flush()
    sync_client_onboarding_status(db, client)
    db.commit()
    db.refresh(client)

    gaps = analyze_onboarding_gaps(db, client)
    check("Sin pendientes tras reemplazar el documento", not gaps.needs_reminder,
          "; ".join(gaps.all_pending_labels()) or "sin pendientes")

    print("\nPASO 8c — Verificación completa aprobada")
    check(
        "Cliente promovido → LISTO_PARA_TRABAJAR",
        client.status == ClientStatus.LISTO_PARA_TRABAJAR.value,
        f"status={client.status}",
    )

    # ── Paso 9: asesor asignado + tablero creado ─────────────────────
    print("\nPASO 9 — Asignación de asesor y creación de tablero")
    assignment = db.execute(
        select(ClientAssignment).where(
            ClientAssignment.client_id == client.id,
            ClientAssignment.unassigned_at.is_(None),
        )
    ).scalar_one_or_none()
    advisor = db.get(User, assignment.advisor_user_id) if assignment else None
    check("Asesor asignado automáticamente", assignment is not None,
          f"asesor={advisor.email if advisor else '-'}")
    check("El asignado tiene rol ADVISOR", bool(advisor and advisor.role.code == "ADVISOR"))

    db.refresh(client)
    board = client.board
    check("Tablero creado", board is not None, f"board_id={board.id if board else '-'}")
    if board is not None:
        lists = sorted(board.lists, key=lambda r: r.position)
        cards = [c for lst in lists for c in lst.cards]
        check("Tablero con listas del template", len(lists) > 0,
              f"{len(lists)} listas: {', '.join(l.title for l in lists)}")
        check("Tablero con tarjetas iniciales", len(cards) > 0, f"{len(cards)} tarjetas")

        # Idempotencia: un nuevo sync sin trabajo real no debe mover el estado
        sync_client_onboarding_status(db, client)
        db.commit()
        db.refresh(client)
        check(
            "Cliente permanece LISTO_PARA_TRABAJAR con el tablero recién creado",
            client.status == ClientStatus.LISTO_PARA_TRABAJAR.value,
            f"status={client.status}",
        )

        # ── Paso 10: trabajo en el tablero ───────────────────────────
        print("\nPASO 10 — Asesor trabaja el tablero")
        from app.models.enums import TaskStatus
        from app.services.boards import BoardService

        bsvc = BoardService(db)
        first_card = cards[0]
        bsvc.update_card_status(
            card=first_card, status=TaskStatus.EN_PROGRESO.value,
            actor=advisor or onboarding, client=client,
        )
        db.refresh(client)
        check(
            "Tarjeta en progreso → ONBOARDING_EN_PROGRESO",
            client.status == ClientStatus.ONBOARDING_EN_PROGRESO.value,
            f"status={client.status}",
        )

        completed_list = next((l for l in lists if l.title == "Completed"), lists[-1])
        for card in cards:
            card.list_id = completed_list.id
        db.flush()
        sync_client_onboarding_status(db, client)
        db.commit()
        db.refresh(client)
        check(
            "Todas las tarjetas completadas → ONBOARDING_COMPLETADO",
            client.status == ClientStatus.ONBOARDING_COMPLETADO.value,
            f"status={client.status}",
        )


def cleanup(db, ids: dict) -> None:
    print("\nLIMPIEZA — Eliminando datos de prueba")
    db.rollback()
    try:
        admin = get_user(db, "admin@epoint.com")
        client_id = ids.get("client")
        if client_id:
            client = db.get(Client, client_id)
            if client is not None and admin is not None:
                ClientService(db).delete_client(actor=admin, client=client)
                print(f"  - Cliente #{client_id} eliminado (portal user incluido)")

        prospect_id = ids.get("prospect")
        if prospect_id:
            prospect = db.get(Prospect, prospect_id)
            if prospect is not None:
                db.delete(prospect)
                print(f"  - Prospecto #{prospect_id} eliminado")

        for key, model in [("calendly_event", CalendlyEvent), ("envelope", DocusignEnvelope),
                           ("payment_link", PaymentLink)]:
            row_id = ids.get(key)
            if row_id:
                row = db.get(model, row_id)
                if row is not None:
                    db.delete(row)
                    print(f"  - {model.__name__} #{row_id} eliminado")

        removed = 0
        for notif in db.execute(
            select(Notification).where(Notification.body.contains(QA_LAST_NAME))
        ).scalars().all():
            db.delete(notif)
            removed += 1
        if removed:
            print(f"  - {removed} notificaciones in-app de QA eliminadas")

        db.commit()
        print("  Limpieza completada.")
    except Exception:
        db.rollback()
        print("  [WARN] Error durante la limpieza:")
        traceback.print_exc()


def main() -> int:
    print("=" * 64)
    print("QA E2E — Flujo prospecto → cliente listo para trabajar")
    print(f"Datos de prueba: {QA_EMAIL} / {QA_PHONE}")
    print("=" * 64)

    db = SessionLocal()
    ids: dict = {}
    crashed = False
    try:
        run_flow(db, ids)
    except Exception:
        crashed = True
        print("\n[FAIL] El flujo se interrumpió con una excepción:")
        traceback.print_exc()
    finally:
        cleanup(db, ids)
        db.close()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    fails = [(s, d) for s, ok, d in RESULTS if not ok]
    print("\n" + "=" * 64)
    print(f"RESULTADO: {passed}/{total} verificaciones OK" + ("  (flujo interrumpido)" if crashed else ""))
    if fails:
        print("\nFallos:")
        for step, detail in fails:
            print(f"  [FAIL] {step}" + (f" — {detail}" if detail else ""))
    print("=" * 64)
    return 1 if (fails or crashed) else 0


if __name__ == "__main__":
    sys.exit(main())
