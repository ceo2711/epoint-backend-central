#!/usr/bin/env python3
"""QA manual/automático de la integración DocuSign."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

import httpx

API = "http://127.0.0.1:8000/api/v1"
ADMIN_EMAIL = "admin@epoint.com"
ADMIN_PASSWORD = "Admin123!"


@dataclass
class QaReport:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def ok(self, msg: str) -> None:
        self.passed.append(msg)
        print(f"  OK  {msg}")

    def fail(self, msg: str) -> None:
        self.failed.append(msg)
        print(f" FAIL {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f" WARN {msg}")


def login(client: httpx.Client) -> str | None:
    r = client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        return None
    return r.json().get("access_token")


def main() -> int:
    report = QaReport()
    print("=== QA DocuSign — ePoint CRM ===\n")

    try:
        client = httpx.Client(timeout=30.0)
    except Exception as exc:
        report.fail(f"No se pudo crear cliente HTTP: {exc}")
        return 1

    # 1. Health
    try:
        r = client.get(f"{API}/health")
        if r.status_code == 200:
            report.ok("Backend responde /health")
        else:
            report.fail(f"/health -> {r.status_code}")
    except httpx.ConnectError:
        report.fail("Backend no está corriendo en http://127.0.0.1:8000")
        print("\nIniciá el backend: cd backend && uvicorn app.main:app --reload")
        return 1

    token = login(client)
    if not token:
        report.fail(f"Login falló ({ADMIN_EMAIL}) — verificá credenciales seed")
        return 1
    report.ok("Login admin OK")
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Connection
    r = client.get(f"{API}/docusign/connection", headers=headers)
    if r.status_code == 200:
        conn = r.json()
        if conn.get("connected"):
            report.ok(f"DocuSign conectado (account={conn.get('account_id', '?')[:8]}…)")
        else:
            report.warn("DocuSign connected=false — faltan DOCUSIGN_* en .env")
    else:
        report.fail(f"GET /docusign/connection -> {r.status_code}: {r.text[:200]}")

    # 3. Consent URL
    r = client.get(f"{API}/docusign/consent-url", headers=headers)
    if r.status_code == 200 and "consent_url" in r.json():
        report.ok("GET /docusign/consent-url genera enlace")
    elif r.status_code == 503:
        report.warn("consent-url -> 503 (DocuSign no configurado)")
    else:
        report.fail(f"GET /docusign/consent-url -> {r.status_code}")

    # 4. Templates
    r = client.get(f"{API}/docusign/templates", headers=headers)
    if r.status_code == 200:
        templates = r.json()
        report.ok(f"GET /docusign/templates -> {len(templates)} plantilla(s)")
        if templates:
            tid = templates[0]["template_id"]
            r2 = client.get(f"{API}/docusign/templates/{tid}", headers=headers)
            if r2.status_code == 200:
                roles = r2.json().get("roles") or []
                report.ok(f"GET /docusign/templates/{{id}} -> {len(roles)} rol(es)")
            else:
                report.fail(f"GET template detail -> {r2.status_code}")
    elif r.status_code == 400 and "consentimiento" in r.text.lower():
        report.warn("Templates -> falta consentimiento JWT (paso 7 docs)")
    elif r.status_code in (502, 503):
        report.warn(f"Templates -> {r.status_code} (DocuSign API)")
    else:
        report.fail(f"GET /docusign/templates -> {r.status_code}: {r.text[:200]}")

    # 5. Envelopes list + sync-pending
    r = client.get(f"{API}/docusign/envelopes", headers=headers)
    if r.status_code == 200:
        report.ok(f"GET /docusign/envelopes -> {len(r.json())} registro(s)")
    else:
        report.fail(f"GET /docusign/envelopes -> {r.status_code}")

    r = client.post(f"{API}/docusign/envelopes/sync-pending", headers=headers, json={})
    if r.status_code == 200:
        envelopes = r.json()
        report.ok(f"POST /docusign/envelopes/sync-pending -> {len(envelopes)} registro(s)")
        completed = [e for e in envelopes if e.get("status", "").lower() == "completed"]
        for env in completed[:2]:
            if env.get("has_signed_document"):
                report.ok(f"Envelope {env['id']} tiene PDF archivado (has_signed_document=true)")
            else:
                report.warn(f"Envelope {env['id']} completed sin PDF en S3 aún")
            rd = client.get(f"{API}/docusign/envelopes/{env['id']}/document", headers=headers)
            if rd.status_code == 200 and "pdf" in rd.headers.get("content-type", "").lower():
                report.ok(f"GET document envelope {env['id']} -> PDF ({len(rd.content)} bytes)")
            elif rd.status_code == 400:
                report.warn(f"Document envelope {env['id']} -> 400 (aún no firmado?)")
            else:
                report.fail(f"GET document envelope {env['id']} -> {rd.status_code}")
    else:
        report.fail(f"POST sync-pending -> {r.status_code}: {r.text[:200]}")

    # 6. Client envelopes (first client)
    r = client.get(f"{API}/clients?page_size=1", headers=headers)
    if r.status_code == 200:
        items = r.json().get("items") or []
        if items:
            cid = items[0]["id"]
            r2 = client.get(f"{API}/docusign/clients/{cid}/envelopes", headers=headers)
            if r2.status_code == 200:
                report.ok(f"GET /docusign/clients/{cid}/envelopes -> {len(r2.json())} contrato(s)")
            else:
                report.fail(f"GET client envelopes -> {r2.status_code}")
        else:
            report.warn("Sin clientes en DB para probar /docusign/clients/{id}/envelopes")
    else:
        report.warn(f"GET /clients -> {r.status_code}")

    # 7. Webhook (dev sin HMAC)
    webhook_body = json.dumps(
        {
            "event": "envelope-completed",
            "data": {"envelopeId": "nonexistent-envelope-id-qa", "envelopeSummary": {"status": "completed"}},
        }
    ).encode()
    r = client.post(
        f"{API}/docusign/webhook",
        content=webhook_body,
        headers={"Content-Type": "application/json"},
    )
    if r.status_code == 200:
        data = r.json()
        if data.get("received") and not data.get("processed"):
            report.ok("POST /docusign/webhook acepta evento (envelope desconocido ignorado)")
        elif data.get("processed"):
            report.ok("POST /docusign/webhook procesó evento")
        else:
            report.warn(f"Webhook respuesta inesperada: {data}")
    elif r.status_code == 401:
        report.warn("Webhook -> 401 (HMAC requerido — set DOCUSIGN_CONNECT_HMAC_KEY o APP_ENV=development)")
    else:
        report.fail(f"POST /docusign/webhook -> {r.status_code}: {r.text[:200]}")

    # 8. Auth guard
    r = client.get(f"{API}/docusign/connection")
    if r.status_code == 401:
        report.ok("Endpoints DocuSign requieren autenticación (401 sin token)")
    else:
        report.fail(f"Sin token debería ser 401, got {r.status_code}")

    # 9. Forbidden role — skip if no sales rep token easily

    print("\n=== Resumen ===")
    print(f"  Pasaron:  {len(report.passed)}")
    print(f"  Fallaron: {len(report.failed)}")
    print(f"  Avisos:   {len(report.warnings)}")
    if report.failed:
        print("\nFallos:")
        for f in report.failed:
            print(f"  - {f}")
    if report.warnings:
        print("\nAvisos:")
        for w in report.warnings:
            print(f"  - {w}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
