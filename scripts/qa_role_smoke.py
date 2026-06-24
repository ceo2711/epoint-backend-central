#!/usr/bin/env python3
"""
Smoke QA por rol contra API en ejecución.

Uso:
  cd backend && python scripts/qa_role_smoke.py
  API_BASE_URL=http://127.0.0.1:8000 python scripts/qa_role_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx

API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API = f"{API_BASE}/api/v1"
TIMEOUT = 30.0

STAFF_USERS = {
    "ADMIN": ("admin@epoint.com", "Admin123!"),
    "SALES_REP": ("vendedor@epoint.com", "Vendedor123!"),
    "ONBOARDING_MANAGER": ("onboarding@epoint.com", "Onboard123!"),
    "ADVISOR": ("asesor@epoint.com", "Asesor123!"),
}


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class RoleReport:
    role: str
    login_ok: bool = False
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.login_ok and all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


def _login(client: httpx.Client, email: str, password: str) -> str | None:
    try:
        res = client.post(f"{API}/auth/login", json={"email": email, "password": password})
        if res.status_code != 200:
            return None
        return res.json().get("access_token")
    except httpx.HTTPError:
        return None


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _check(
    client: httpx.Client,
    token: str,
    *,
    name: str,
    method: str,
    path: str,
    expect: int | tuple[int, ...],
    json_body: dict | None = None,
) -> CheckResult:
    expected = (expect,) if isinstance(expect, int) else expect
    try:
        res = client.request(
            method,
            f"{API}{path}",
            headers=_auth_headers(token),
            json=json_body,
            timeout=TIMEOUT,
        )
        ok = res.status_code in expected
        detail = f"HTTP {res.status_code}" if ok else f"HTTP {res.status_code}, esperado {expected}"
        if not ok and res.text:
            detail += f" — {res.text[:200]}"
        return CheckResult(name=name, passed=ok, detail=detail)
    except httpx.HTTPError as exc:
        return CheckResult(name=name, passed=False, detail=str(exc))


def _run_staff_role(client: httpx.Client, role: str, email: str, password: str) -> RoleReport:
    report = RoleReport(role=role)
    token = _login(client, email, password)
    if not token:
        report.checks.append(CheckResult("login", False, "Credenciales inválidas o API caída"))
        return report

    report.login_ok = True
    report.checks.append(CheckResult("login", True, email))

    me = client.get(f"{API}/auth/me", headers=_auth_headers(token))
    if me.status_code == 200 and me.json().get("role", {}).get("code") == role:
        report.checks.append(CheckResult("auth/me role", True, role))
    else:
        report.checks.append(
            CheckResult(
                "auth/me role",
                False,
                f"rol={me.json().get('role', {}).get('code') if me.status_code == 200 else me.status_code}",
            )
        )

    # Matriz por rol
    if role == "ADMIN":
        for name, method, path, expect in [
            ("GET /users", "GET", "/users", 200),
            ("GET /roles", "GET", "/roles", 200),
            ("GET /areas", "GET", "/areas", 200),
            ("GET /merchants", "GET", "/merchants", 200),
            ("GET /clients", "GET", "/clients", 200),
            ("GET /clients/stats", "GET", "/clients/stats", 200),
            ("portal bloqueado", "GET", "/portal/me", (403, 404)),
        ]:
            report.checks.append(_check(client, token, name=name, method=method, path=path, expect=expect))

    elif role == "SALES_REP":
        for name, method, path, expect in [
            ("GET /clients", "GET", "/clients", 200),
            ("GET /clients/stats", "GET", "/clients/stats", 200),
            ("GET /merchants/options", "GET", "/merchants/options", 200),
            ("users denegado", "GET", "/users", 403),
            ("merchants denegado", "GET", "/merchants", 403),
            ("advisors denegado", "GET", "/advisors", 403),
            ("chatbot", "POST", "/chatbot/message", 200),
        ]:
            body = {"message": "hola", "history": [], "locale": "es"} if method == "POST" else None
            report.checks.append(
                _check(client, token, name=name, method=method, path=path, expect=expect, json_body=body)
            )

    elif role == "ONBOARDING_MANAGER":
        for name, method, path, expect in [
            ("GET /clients", "GET", "/clients", 200),
            ("GET /clients onboarding", "GET", "/clients?onboarding_only=true", 200),
            ("GET /advisors", "GET", "/advisors", 200),
            ("users denegado", "GET", "/users", 403),
            ("chatbot", "POST", "/chatbot/message", 200),
        ]:
            body = {"message": "hola", "history": [], "locale": "es"} if method == "POST" else None
            report.checks.append(
                _check(client, token, name=name, method=method, path=path, expect=expect, json_body=body)
            )

    elif role == "ADVISOR":
        for name, method, path, expect in [
            ("GET /clients", "GET", "/clients", 200),
            ("approve denegado", "GET", "/advisors", 403),
            ("users denegado", "GET", "/users", 403),
            ("chatbot", "POST", "/chatbot/message", 200),
        ]:
            body = {"message": "hola", "history": [], "locale": "es"} if method == "POST" else None
            report.checks.append(
                _check(client, token, name=name, method=method, path=path, expect=expect, json_body=body)
            )

    return report


def _find_portal_client_credentials(client: httpx.Client, admin_token: str) -> tuple[str, str] | None:
    """Busca credenciales de un cliente portal aprobado."""
    override_email = os.getenv("QA_CLIENT_EMAIL")
    override_pass = os.getenv("QA_CLIENT_PASSWORD")
    if override_email and override_pass:
        return override_email, override_pass

    res = client.get(
        f"{API}/clients",
        headers=_auth_headers(admin_token),
        params={"page_size": 100},
    )
    if res.status_code != 200:
        return None

    approved_statuses = {
        "EN_CARGA_DATOS",
        "APROBADO_PARA_ONBOARDING",
        "DOCUMENTACION_PENDIENTE",
        "COMPLETADO",
    }
    for item in res.json().get("items", []):
        if not item.get("approved_at") and item.get("status") not in approved_statuses:
            continue
        email = item.get("email")
        if email and override_pass:
            return email, override_pass

    return None


def _run_client_role(client: httpx.Client, admin_token: str) -> RoleReport:
    report = RoleReport(role="CLIENT")
    creds = _find_portal_client_credentials(client, admin_token)
    if not creds:
        report.checks.append(
            CheckResult(
                "login",
                False,
                "Sin cliente aprobado o falta QA_CLIENT_PASSWORD. "
                "Ej: QA_CLIENT_EMAIL=angela@example.com QA_CLIENT_PASSWORD=TempPass123!",
            )
        )
        return report

    email, password = creds
    token = _login(client, email, password)
    if not token:
        report.checks.append(
            CheckResult(
                "login",
                False,
                f"No se pudo iniciar sesión como {email}. Definí QA_CLIENT_PASSWORD con la contraseña temporal.",
            )
        )
        return report

    report.login_ok = True
    report.checks.append(CheckResult("login", True, email))

    for name, method, path, expect in [
        ("GET /portal/me", "GET", "/portal/me", 200),
        ("GET /portal/documents", "GET", "/portal/documents", 200),
        ("staff clients denegado", "GET", "/clients", 403),
        ("users denegado", "GET", "/users", 403),
        ("chatbot", "POST", "/chatbot/message", 200),
    ]:
        body = {"message": "hola", "history": [], "locale": "es"} if method == "POST" else None
        report.checks.append(
            _check(client, token, name=name, method=method, path=path, expect=expect, json_body=body)
        )

    return report


def _print_report(reports: list[RoleReport]) -> int:
    print("\n" + "=" * 60)
    print("QA SMOKE — ePoint CRM por rol")
    print(f"API: {API}")
    print("=" * 60)

    failures = 0
    for report in reports:
        status = "PASS" if report.passed else "FAIL"
        print(f"\n[{status}] {report.role}")
        if not report.login_ok:
            for c in report.checks:
                print(f"  [X] {c.name}: {c.detail}")
            failures += 1
            continue
        for c in report.checks:
            mark = "[OK]" if c.passed else "[X]"
            print(f"  {mark} {c.name}" + (f" — {c.detail}" if c.detail and not c.passed else ""))
        if not report.passed:
            failures += 1

    print("\n" + "-" * 60)
    total = len(reports)
    passed = total - failures
    print(f"Resumen: {passed}/{total} roles OK")
    print("-" * 60 + "\n")
    return 1 if failures else 0


def main() -> int:
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            health = client.get(f"{API}/health")
            if health.status_code != 200:
                print(f"API no disponible en {API}/health (HTTP {health.status_code})")
                return 2
    except httpx.HTTPError as exc:
        print(f"No se pudo conectar a {API}: {exc}")
        print("Levantá el backend: cd backend && uvicorn app.main:app --reload")
        return 2

    reports: list[RoleReport] = []

    with httpx.Client(timeout=TIMEOUT) as client:
        for role, (email, password) in STAFF_USERS.items():
            reports.append(_run_staff_role(client, role, email, password))

        admin_token = _login(client, *STAFF_USERS["ADMIN"])
        if admin_token:
            reports.append(_run_client_role(client, admin_token))
        else:
            reports.append(
                RoleReport(
                    role="CLIENT",
                    checks=[CheckResult("login", False, "No se pudo autenticar admin para buscar cliente portal")],
                )
            )

    return _print_report(reports)


if __name__ == "__main__":
    sys.exit(main())
