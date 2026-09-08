"""Ensayo en seco de la migración de clientes (no escribe en la base).

Uso:
  python scripts/dry_run_client_migration.py
  python scripts/dry_run_client_migration.py --prod
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

STANDARD_PAYMENT = Decimal("3000.00")
MIGRATION_NOTE = "Cliente ingresado en la migración."
SKIP_FOLDERS = {
    "Albani Parra",
    "Karol Nieto",
}
MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
DOC_STEMS = {
    "ssn": "SSN_CARD",
    "id front": "DRIVERS_LICENSE_FRONT",
    "id back": "DRIVERS_LICENSE_BACK",
    "utility bill": "UTILITY_BILL",
    "statement": "BANK_STATEMENT",
    "contrato": "CONTRATO",
    "passport": "PASSPORT",
}


@dataclass
class ParsedClient:
    lote: str
    folder: str
    path: str
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    ssn_present: bool = False
    ssn_ok: bool = False
    dob: str = ""
    address_current_raw: str = ""
    address_previous_raw: str = ""
    address_current: dict | None = None
    address_previous: dict | None = None
    vehicle: dict | None = None
    docs: dict[str, str] = field(default_factory=dict)
    extra_files: list[str] = field(default_factory=list)
    partial: bool = False
    debt: Decimal | None = None
    paid: Decimal = STANDARD_PAYMENT
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _pi_folder(client_dir: Path) -> Path | None:
    exact = client_dir / "Personal Information"
    if exact.is_dir():
        return exact
    for child in client_dir.iterdir():
        if child.is_dir() and child.name.lower().startswith("personal info"):
            return child
    return None


def _field(text: str, label: str) -> str:
    pattern = rf"(?im)^{re.escape(label)}\s*:\s*(.*)$"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _split_name(full_name: str) -> tuple[str, str]:
    parts = [p for p in full_name.strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], "."
    return parts[0], " ".join(parts[1:])


def _parse_since(blob: str) -> tuple[int | None, int | None]:
    match = re.search(
        r"desde\s+(?:(\d{1,2})\s+de\s+)?([a-záéíóú]+)\s+de\s+(\d{4})",
        blob,
        re.I,
    )
    if not match:
        return None, None
    month_name = re.sub(r"[áéíóú]", lambda m: {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u"}[m.group()], match.group(2).lower())
    month = MONTHS_ES.get(month_name)
    year = int(match.group(3))
    return month, year


def _parse_address(raw: str) -> dict | None:
    value = raw.strip()
    if not value or value.lower() in {"no aplica", "n/a", "na", "-"}:
        return None
    since_month, since_year = _parse_since(value)
    value = re.sub(r"\s*\(desde.*?\)\s*$", "", value, flags=re.I).strip()
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) < 2:
        return {
            "street": value[:255],
            "city": "",
            "state": "",
            "zip_code": "",
            "residence_since_month": since_month,
            "residence_since_year": since_year,
            "raw": raw,
        }
    last = parts[-1]
    state_zip = re.match(r"^([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$", last)
    if state_zip:
        state, zip_code = state_zip.group(1), state_zip.group(2)
        city = parts[-2] if len(parts) >= 2 else ""
        street = ", ".join(parts[:-2]) if len(parts) > 2 else (parts[0] if len(parts) == 2 else "")
        if len(parts) == 2:
            street = ""
            city = parts[0]
        else:
            street = ", ".join(parts[:-2])
            city = parts[-2]
        return {
            "street": street[:255],
            "city": city[:100],
            "state": state,
            "zip_code": zip_code[:20],
            "residence_since_month": since_month,
            "residence_since_year": since_year,
            "raw": raw,
        }
    return {
        "street": value[:255],
        "city": "",
        "state": "",
        "zip_code": "",
        "residence_since_month": since_month,
        "residence_since_year": since_year,
        "raw": raw,
    }


def _parse_vehicle(text: str) -> dict | None:
    model = _field(text, "Modelo")
    year = _field(text, "Año") or _field(text, "Ano")
    color = _field(text, "Color")
    plate = _field(text, "Matrícula") or _field(text, "Matricula")
    if not model and not year and not color and not plate:
        return None
    year_int = None
    if year.isdigit():
        year_int = int(year)
    if not model or year_int is None or not color:
        return {
            "model": model,
            "year": year_int,
            "color": color,
            "license_plate": plate or None,
            "incomplete": True,
        }
    return {
        "model": model,
        "year": year_int,
        "color": color,
        "license_plate": plate or None,
        "incomplete": False,
    }


def _parse_finanzas(path: Path) -> Decimal | None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"(?:ADEUDA(?:DO)?)\s*:?\s*\$?\s*([0-9]+(?:[.,][0-9]+)?)", raw, re.I)
    if not match:
        return None
    return Decimal(match.group(1).replace(",", "."))


def _classify_doc(name: str) -> str | None:
    stem = Path(name).stem.lower().strip()
    stem = re.sub(r"\(\d+\)$", "", stem).strip()
    for key, doc_type in DOC_STEMS.items():
        if stem == key:
            return doc_type
    return None


def parse_client(lote: str, client_dir: Path) -> ParsedClient:
    parsed = ParsedClient(lote=lote, folder=client_dir.name, path=str(client_dir))
    pi = _pi_folder(client_dir)
    if pi is None:
        parsed.errors.append("sin Personal Information")
        return parsed

    txts = [p for p in pi.glob("*.txt") if p.name.upper() not in {"FINANZAS.TXT"} and "informe" not in p.name.lower()]
    expected = pi / f"{client_dir.name}.txt"
    data_txt = expected if expected.exists() else (txts[0] if txts else None)
    if data_txt is None:
        parsed.errors.append("sin txt de datos")
        return parsed

    text = data_txt.read_text(encoding="utf-8", errors="replace")
    parsed.full_name = _field(text, "Nombre completo")
    parsed.first_name, parsed.last_name = _split_name(parsed.full_name)
    parsed.email = (_field(text, "Correo electrónico") or _field(text, "Correo electronico")).lower().strip()
    parsed.phone = _field(text, "Teléfono") or _field(text, "Telefono")
    ssn = _field(text, "SSN")
    parsed.ssn_present = bool(ssn)
    parsed.ssn_ok = bool(re.fullmatch(r"\d{3}-\d{2}-\d{4}", ssn))
    parsed.dob = _field(text, "Fecha Nacimiento")
    parsed.address_current_raw = _field(text, "Dirección actual") or _field(text, "Direccion actual")
    parsed.address_previous_raw = _field(text, "Dirección anterior") or _field(text, "Direccion anterior")
    parsed.address_current = _parse_address(parsed.address_current_raw)
    parsed.address_previous = _parse_address(parsed.address_previous_raw)
    parsed.vehicle = _parse_vehicle(text)

    if not parsed.full_name:
        parsed.errors.append("nombre vacío")
    if not parsed.email or "@" not in parsed.email:
        parsed.errors.append("email inválido")
    if not parsed.phone or len(parsed.phone) < 5:
        parsed.errors.append("teléfono vacío")
    if parsed.phone and len(parsed.phone) > 30:
        parsed.errors.append("teléfono > 30 caracteres")
    if parsed.ssn_present and not parsed.ssn_ok:
        parsed.warnings.append("SSN con formato no estándar")
    if not parsed.ssn_present:
        parsed.warnings.append("SSN vacío en el txt")
    if parsed.dob and not re.fullmatch(r"\d{2}/\d{2}/\d{4}", parsed.dob):
        parsed.warnings.append(f"fecha de nacimiento no MM/DD/YYYY: {parsed.dob}")
    if parsed.address_current and not parsed.address_current.get("state"):
        parsed.warnings.append("dirección actual no se pudo partir en ciudad/estado/ZIP")
    if parsed.vehicle and parsed.vehicle.get("incomplete"):
        parsed.warnings.append(
            "vehículo incompleto (se migra el cliente sin vehículo; onboarding puede completarlo después)"
        )

    fin = pi / "FINANZAS.txt"
    if fin.exists():
        parsed.partial = True
        parsed.debt = _parse_finanzas(fin)
        if parsed.debt is None:
            parsed.errors.append("FINANZAS.txt sin monto ADEUDA")
        elif parsed.debt >= STANDARD_PAYMENT:
            parsed.errors.append(f"deuda {parsed.debt} no es menor a 3000")
        else:
            parsed.paid = STANDARD_PAYMENT - parsed.debt

    for file in pi.iterdir():
        if not file.is_file():
            continue
        if file.suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
            if file.suffix.lower() in {".txt", ".docx"}:
                continue
            parsed.extra_files.append(file.name)
            continue
        doc_type = _classify_doc(file.name)
        if doc_type:
            parsed.docs[doc_type] = file.name
        else:
            parsed.extra_files.append(file.name)

    if "SSN_CARD" not in parsed.docs:
        parsed.errors.append("falta SSN.pdf")
    if "CONTRATO" not in parsed.docs:
        parsed.errors.append("falta CONTRATO.pdf")
    if "DRIVERS_LICENSE_FRONT" not in parsed.docs:
        parsed.errors.append("falta ID FRONT")
    if "DRIVERS_LICENSE_BACK" not in parsed.docs:
        parsed.errors.append("falta ID BACK")
    if "UTILITY_BILL" not in parsed.docs and "BANK_STATEMENT" not in parsed.docs:
        parsed.errors.append("falta comprobante de domicilio")

    return parsed


def scan_root(root: Path) -> list[ParsedClient]:
    clients: list[ParsedClient] = []
    skipped: list[str] = []
    for lote_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name.lower().startswith("lote")):
        for client_dir in sorted(p for p in lote_dir.iterdir() if p.is_dir()):
            if client_dir.name in SKIP_FOLDERS:
                skipped.append(f"{lote_dir.name} / {client_dir.name}")
                continue
            clients.append(parse_client(lote_dir.name, client_dir))
    return clients, skipped


def lookup_prod(emails: list[str]) -> dict:
    import psycopg2

    url = os.environ.get("PROD_DB")
    if not url:
        raise RuntimeError("Falta PROD_DB")
    conn = psycopg2.connect(url, sslmode="require", connect_timeout=20)
    cur = conn.cursor()
    cur.execute("SELECT id, name, code FROM sedes WHERE lower(name) = lower(%s) OR lower(code) = lower(%s)", ("Headquarters", "headquarters"))
    sedes = cur.fetchall()
    cur.execute(
        "SELECT id, code, name, sede_id, is_active FROM merchants WHERE lower(code) = lower(%s) OR lower(name) = lower(%s)",
        ("epoint-credits", "epoint-credits"),
    )
    merchants = cur.fetchall()
    cur.execute("SELECT code, name, is_active FROM sources WHERE code = 'OTHER'")
    source = cur.fetchone()
    existing = []
    if emails:
        cur.execute(
            "SELECT id, email, first_name, last_name, status FROM clients WHERE lower(email) = ANY(%s)",
            ([e.lower() for e in emails],),
        )
        existing = cur.fetchall()
    cur.close()
    conn.close()
    return {"sedes": sedes, "merchants": merchants, "source": source, "existing": existing}


def write_report(
    clients: list[ParsedClient],
    prod: dict | None,
    out_path: Path,
    skipped: list[str] | None = None,
) -> None:
    ok = [c for c in clients if not c.errors]
    bad = [c for c in clients if c.errors]
    lines: list[str] = []
    lines.append("PRUEBA DE MIGRACIÓN (sin escribir en la base)")
    lines.append("=" * 60)
    lines.append("")
    lines.append("Reglas fijas")
    lines.append("- Sede: Headquarters")
    lines.append("- Comercio: epoint-credits")
    lines.append("- Source: OTHER")
    lines.append("- Lead calificado: vacío")
    lines.append(f"- Nota: {MIGRATION_NOTE}")
    lines.append("- Sin email de bienvenida")
    lines.append("- Pago: USD 3000 si no hay FINANZAS.txt; si hay, pagado = 3000 - ADEUDA")
    lines.append("- Contrato: CONTRATO.pdf como contrato firmado a mano")
    lines.append("- Nombre: primer token = nombre, el resto = apellido")
    lines.append("")
    lines.append("Nota del CRM: la ficha de cliente no tiene campo 'notes'.")
    lines.append("En la migración real se registrará en auditoría y, al crear el tablero,")
    lines.append("una card 'Migración' con ese texto.")
    lines.append("")
    if skipped:
        lines.append("Descartados a pedido:")
        for item in skipped:
            lines.append(f"- {item}")
        lines.append("")
    lines.append(f"Expedientes leídos (sin descartados): {len(clients)}")
    lines.append(f"Listos (sin errores de archivo): {len(ok)}")
    lines.append(f"Con error de archivo: {len(bad)}")
    lines.append(f"Pagos completos: {sum(1 for c in ok if not c.partial)}")
    lines.append(f"Pagos parciales: {sum(1 for c in ok if c.partial)}")
    lines.append("")

    if prod:
        lines.append("Validación contra PRODUCCIÓN (solo lectura)")
        if prod["sedes"]:
            for row in prod["sedes"]:
                lines.append(f"- Sede encontrada: id={row[0]} name={row[1]!r} code={row[2]!r}")
        else:
            lines.append("- ERROR: no está la sede Headquarters")
        if prod["merchants"]:
            for row in prod["merchants"]:
                lines.append(
                    f"- Comercio encontrado: id={row[0]} code={row[1]!r} name={row[2]!r} sede_id={row[3]} active={row[4]}"
                )
        else:
            lines.append("- ERROR: no está el comercio epoint-credits")
        if prod["source"]:
            lines.append(f"- Source OTHER: {prod['source'][1]} active={prod['source'][2]}")
        else:
            lines.append("- ERROR: no está la source OTHER")
        if prod["existing"]:
            lines.append(f"- Mails que YA existen en prod ({len(prod['existing'])}):")
            for row in prod["existing"]:
                lines.append(f"    #{row[0]} {row[2]} {row[3]} <{row[1]}> status={row[4]}")
        else:
            lines.append("- Ningún mail del lote está ya en producción")
        lines.append("")

    emails = [c.email for c in ok if c.email]
    dupes = [email for email, n in Counter(emails).items() if n > 1]
    if dupes:
        lines.append("Mails duplicados DENTRO de los lotes:")
        for email in dupes:
            names = [c.folder for c in ok if c.email == email]
            lines.append(f"  {email}: {', '.join(names)}")
        lines.append("")

    lines.append("PAGOS PARCIALES")
    for client in ok:
        if client.partial:
            lines.append(f"- {client.lote} / {client.folder}: adeuda {client.debt} → pagado {client.paid}")
    lines.append("")

    if bad:
        lines.append("ERRORES DE ARCHIVO (no se migrarían)")
        for client in bad:
            lines.append(f"- {client.lote} / {client.folder}: {'; '.join(client.errors)}")
        lines.append("")

    warned = [c for c in ok if c.warnings]
    lines.append(f"Advertencias (sí se migrarían, revisar): {len(warned)}")
    for client in warned:
        lines.append(f"- {client.lote} / {client.folder}: {'; '.join(client.warnings)}")
    lines.append("")
    lines.append("LISTADO LISTO PARA MIGRAR")
    by_lote: dict[str, list[ParsedClient]] = defaultdict(list)
    for client in ok:
        by_lote[client.lote].append(client)
    for lote, rows in by_lote.items():
        lines.append(f"\n{lote} ({len(rows)})")
        for client in rows:
            pay = f"parcial {client.paid}" if client.partial else "3000 completo"
            lines.append(
                f"  - {client.first_name} {client.last_name} | {client.email} | {client.phone} | {pay}"
            )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out_path.read_text(encoding="utf-8"))
    print(f"\nReporte guardado en: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default=r"C:\Users\alexis\Documents\migracion epoint\Clients Data Migra",
    )
    parser.add_argument("--prod", action="store_true", help="Validar sede/comercio/mails contra producción")
    parser.add_argument(
        "--out",
        default=r"C:\Users\alexis\Documents\migracion epoint\reporte-prueba-migracion.txt",
    )
    args = parser.parse_args()
    root = Path(args.root)
    clients, skipped = scan_root(root)
    prod = lookup_prod([c.email for c in clients if c.email]) if args.prod else None
    write_report(clients, prod, Path(args.out), skipped=skipped)


if __name__ == "__main__":
    main()
