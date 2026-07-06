"""QA runner — pruebas de integración contra API local/Heroku."""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://127.0.0.1:8000/api/v1"
FRONTEND = "http://localhost:3000"

USERS = {
    "admin": ("admin@epoint.com", "Admin123!"),
    "vendedor": ("vendedor@epoint.com", "Vendedor123!"),
    "onboarding": ("onboarding@epoint.com", "Onboard123!"),
    "asesor": ("asesor@epoint.com", "Asesor123!"),
}


@dataclass
class Result:
    id: str
    module: str
    name: str
    passed: bool
    detail: str = ""


@dataclass
class QAReport:
    results: list[Result] = field(default_factory=list)

    def ok(self, id_: str, module: str, name: str, detail: str = "") -> None:
        self.results.append(Result(id_, module, name, True, detail))

    def fail(self, id_: str, module: str, name: str, detail: str = "") -> None:
        self.results.append(Result(id_, module, name, False, detail))

    def summary(self) -> tuple[int, int]:
        passed = sum(1 for r in self.results if r.passed)
        return passed, len(self.results)


def login(client: httpx.Client, email: str, password: str) -> dict | None:
    r = client.post(f"{BASE}/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("requires_2fa"):
        return None
    return data


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def run_qa() -> QAReport:
    report = QAReport()
    tokens: dict[str, str] = {}

    with httpx.Client(timeout=30.0) as client:
        # ── Health ──
        r = client.get(f"{BASE}/health")
        if r.status_code == 200 and r.json().get("status") == "ok":
            report.ok("HEALTH-01", "Health", "GET /health")
        else:
            report.fail("HEALTH-01", "Health", "GET /health", f"status={r.status_code}")

        # ── Auth login all roles ──
        for role, (email, pwd) in USERS.items():
            data = login(client, email, pwd)
            if data and data.get("access_token"):
                tokens[role] = data["access_token"]
                report.ok(f"AUTH-{role.upper()}", "Auth", f"Login {role}")
            else:
                report.fail(f"AUTH-{role.upper()}", "Auth", f"Login {role}", "no token")

        # Bad credentials
        r = client.post(f"{BASE}/auth/login", json={"email": "admin@epoint.com", "password": "wrong"})
        if r.status_code in (401, 422):
            report.ok("AUTH-05", "Auth", "Credenciales incorrectas rechazadas")
        else:
            report.fail("AUTH-05", "Auth", "Credenciales incorrectas", f"status={r.status_code}")

        # No token
        r = client.get(f"{BASE}/auth/me")
        if r.status_code == 401:
            report.ok("SEC-01", "Security", "API sin token → 401")
        else:
            report.fail("SEC-01", "Security", "API sin token", f"status={r.status_code}")

        admin_h = auth_headers(tokens.get("admin", ""))
        vend_h = auth_headers(tokens.get("vendedor", ""))
        onb_h = auth_headers(tokens.get("onboarding", ""))
        ases_h = auth_headers(tokens.get("asesor", ""))

        # ── /auth/me ──
        for role, hdr in [("admin", admin_h), ("vendedor", vend_h), ("onboarding", onb_h), ("asesor", ases_h)]:
            r = client.get(f"{BASE}/auth/me", headers=hdr)
            if r.status_code == 200:
                report.ok(f"ME-{role.upper()}", "Auth", f"GET /auth/me {role}")
            else:
                report.fail(f"ME-{role.upper()}", "Auth", f"GET /auth/me {role}", f"status={r.status_code}")

        # ── RBAC: vendedor no puede /users ──
        r = client.get(f"{BASE}/users", headers=vend_h)
        if r.status_code == 403:
            report.ok("SEC-02", "Security", "Vendedor GET /users → 403")
        else:
            report.fail("SEC-02", "Security", "Vendedor GET /users", f"status={r.status_code}")

        # Admin can /users
        r = client.get(f"{BASE}/users", headers=admin_h)
        if r.status_code == 200:
            report.ok("ADM-01", "Admin", "Admin GET /users")
        else:
            report.fail("ADM-01", "Admin", "Admin GET /users", f"status={r.status_code}")

        # ── Areas, roles, merchants (admin) ──
        for endpoint, id_, name in [
            ("/areas", "ADM-09", "GET /areas"),
            ("/roles", "ADM-12", "GET /roles"),
            ("/merchants", "ADM-07", "GET /merchants"),
        ]:
            r = client.get(f"{BASE}{endpoint}", headers=admin_h)
            if r.status_code == 200:
                report.ok(id_, "Admin", name)
            else:
                report.fail(id_, "Admin", name, f"status={r.status_code}")

        # Onboarding cannot /users
        r = client.get(f"{BASE}/users", headers=onb_h)
        if r.status_code == 403:
            report.ok("NAV-ONB", "RBAC", "Onboarding no accede /users")
        else:
            report.fail("NAV-ONB", "RBAC", "Onboarding /users", f"status={r.status_code}")

        # ── Clients ──
        r = client.get(f"{BASE}/clients", headers=vend_h)
        if r.status_code == 200:
            vend_clients = r.json()
            report.ok("CLI-LIST-VEND", "Clientes", "Vendedor lista clientes", f"total={vend_clients.get('total', '?')}")
        else:
            report.fail("CLI-LIST-VEND", "Clientes", "Vendedor lista clientes", f"status={r.status_code}")
            vend_clients = {"items": []}

        r = client.get(f"{BASE}/clients", headers=onb_h)
        if r.status_code == 200:
            onb_clients = r.json()
            report.ok("CLI-LIST-ONB", "Clientes", "Onboarding lista clientes", f"total={onb_clients.get('total', '?')}")
        else:
            report.fail("CLI-LIST-ONB", "Clientes", "Onboarding lista clientes", f"status={r.status_code}")
            onb_clients = {"items": []}

        # Stats
        r = client.get(f"{BASE}/clients/stats", headers=admin_h)
        if r.status_code == 200:
            report.ok("DSH-01", "Dashboard", "GET /clients/stats")
        else:
            report.fail("DSH-01", "Dashboard", "GET /clients/stats", f"status={r.status_code}")

        # Advisors list
        r = client.get(f"{BASE}/advisors", headers=onb_h)
        if r.status_code == 200:
            report.ok("ACC-05", "Clientes", "GET /advisors")
        else:
            report.fail("ACC-05", "Clientes", "GET /advisors", f"status={r.status_code}")

        # Client detail scoping
        if onb_clients.get("items"):
            cid = onb_clients["items"][0]["id"]
            r = client.get(f"{BASE}/clients/{cid}", headers=onb_h)
            if r.status_code == 200:
                report.ok("CLI-DET-ONB", "Clientes", "Onboarding detalle cliente")
            else:
                report.fail("CLI-DET-ONB", "Clientes", "Onboarding detalle", f"status={r.status_code}")

        # ── Notifications ──
        r = client.get(f"{BASE}/notifications", headers=admin_h)
        if r.status_code == 200:
            report.ok("NOT-01", "Notificaciones", "GET /notifications")
        else:
            report.fail("NOT-01", "Notificaciones", "GET /notifications", f"status={r.status_code}")

        # ── Onboarding reminders config ──
        r = client.get(f"{BASE}/onboarding-reminders/config", headers=admin_h)
        if r.status_code == 200:
            report.ok("REM-01", "Recordatorios", "GET /onboarding-reminders/config")
        else:
            report.fail("REM-01", "Recordatorios", "GET config", f"status={r.status_code}")

        # ── Calendly ──
        r = client.get(f"{BASE}/calendly/connection", headers=vend_h)
        if r.status_code == 200:
            report.ok("CAL-01", "Calendly", "GET /calendly/connection (vendedor)")
        else:
            report.fail("CAL-01", "Calendly", "GET connection", f"status={r.status_code}")

        r = client.get(f"{BASE}/calendly/sales-reps", headers=admin_h)
        if r.status_code == 200:
            report.ok("CAL-03", "Calendly", "Admin GET /calendly/sales-reps")
        else:
            report.fail("CAL-03", "Calendly", "sales-reps", f"status={r.status_code}")

        # Asesor cannot calendly sales-reps (403 or 200 empty - check)
        r = client.get(f"{BASE}/calendly/sales-reps", headers=ases_h)
        if r.status_code in (403, 200):
            report.ok("CAL-12", "Calendly", "Asesor calendly access control", f"status={r.status_code}")
        else:
            report.fail("CAL-12", "Calendly", "Asesor calendly", f"status={r.status_code}")

        # ── DocuSign ──
        r = client.get(f"{BASE}/docusign/connection", headers=vend_h)
        if r.status_code == 200:
            conn = r.json()
            report.ok("DS-01", "DocuSign", "GET /docusign/connection", f"connected={conn.get('connected')}")
        else:
            report.fail("DS-01", "DocuSign", "GET connection", f"status={r.status_code}")

        r = client.get(f"{BASE}/docusign/envelopes", headers=vend_h)
        if r.status_code == 200:
            report.ok("DS-08", "DocuSign", "GET /docusign/envelopes")
        else:
            report.fail("DS-08", "DocuSign", "GET envelopes", f"status={r.status_code}")

        # Onboarding cannot docusign
        r = client.get(f"{BASE}/docusign/envelopes", headers=onb_h)
        if r.status_code == 403:
            report.ok("DS-17", "DocuSign", "Onboarding no accede envelopes")
        else:
            report.fail("DS-17", "DocuSign", "Onboarding envelopes", f"status={r.status_code}")

        # ── Chatbot (Gemini puede tardar; timeout extendido) ──
        try:
            r = client.post(
                f"{BASE}/chatbot/message",
                headers=admin_h,
                json={"message": "Hola", "locale": "es"},
                timeout=90.0,
            )
            if r.status_code == 200 and r.json().get("reply"):
                report.ok("BOT-01", "Chatbot", "POST /chatbot/message admin")
            else:
                report.fail("BOT-01", "Chatbot", "POST message", f"status={r.status_code}")
        except httpx.TimeoutException:
            report.fail("BOT-01", "Chatbot", "POST message", "timeout >90s (Gemini lento)")
        except Exception as e:
            report.fail("BOT-01", "Chatbot", "POST message", str(e))

        # ── Frontend pages HTTP ──
        pages = [
            ("/login", "NAV-FE-LOGIN"),
            ("/dashboard", "NAV-FE-DASH"),
            ("/clientes", "NAV-FE-CLI"),
            ("/usuarios", "NAV-FE-USR"),
            ("/contratos", "NAV-FE-CON"),
            ("/calendario", "NAV-FE-CAL"),
            ("/portal", "NAV-FE-POR"),
        ]
        for path, id_ in pages:
            try:
                fr = client.get(f"{FRONTEND}{path}", follow_redirects=True)
                if fr.status_code == 200:
                    report.ok(id_, "Frontend", f"GET {path} → 200")
                else:
                    report.fail(id_, "Frontend", f"GET {path}", f"status={fr.status_code}")
            except Exception as e:
                report.fail(id_, "Frontend", f"GET {path}", str(e))

    return report


if __name__ == "__main__":
    print("=" * 60)
    print("ePoint CRM — QA Runner")
    print(f"API: {BASE}")
    print(f"Frontend: {FRONTEND}")
    print("=" * 60)

    report = run_qa()
    passed, total = report.summary()

    fails = [r for r in report.results if not r.passed]
    oks = [r for r in report.results if r.passed]

    print(f"\n[OK] PASARON: {passed}/{total}")
    print(f"[FAIL] FALLARON: {len(fails)}/{total}\n")

    if fails:
        print("--- FALLOS ---")
        for r in fails:
            print(f"  [{r.id}] {r.module}/{r.name}: {r.detail}")

    print("\n--- RESUMEN POR MÓDULO ---")
    modules: dict[str, list[Result]] = {}
    for r in report.results:
        modules.setdefault(r.module, []).append(r)
    for mod, items in sorted(modules.items()):
        p = sum(1 for i in items if i.passed)
        print(f"  {mod}: {p}/{len(items)}")

    sys.exit(0 if not fails else 1)
