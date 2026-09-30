"""Medios de pago declarados en PAYMENT_METHODS.

Formato: codigo:Etiqueta,codigo:Etiqueta
Ejemplo: authorize:Authorize.net,paypal:PayPal,zelle:Zelle
El código se guarda en la base (máximo 20 caracteres). La etiqueta es lo que ve el vendedor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_PAYMENT_METHODS = "authorize:Authorize.net,paypal:PayPal"
_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,19}$")


@dataclass(frozen=True, slots=True)
class PaymentMethodOption:
    code: str
    label: str


_FALLBACK_LABELS = {
    "authorize": "Authorize.net",
    "paypal": "PayPal",
    "stripe": "Stripe",
}


def label_for_payment_method(code: str, options: list[PaymentMethodOption] | None = None) -> str:
    for item in options or []:
        if item.code == code:
            return item.label
    return _FALLBACK_LABELS.get(code, code)


def parse_payment_methods(raw: str | None, *, _fallback: bool = True) -> list[PaymentMethodOption]:
    source = (raw or "").strip() or DEFAULT_PAYMENT_METHODS
    options: list[PaymentMethodOption] = []
    seen: set[str] = set()
    for part in source.split(","):
        piece = part.strip()
        if not piece:
            continue
        if ":" in piece:
            code_raw, label_raw = piece.split(":", 1)
        else:
            code_raw = label_raw = piece
        code = code_raw.strip().lower()
        label = label_raw.strip()
        if not _CODE_RE.match(code) or not label or code in seen:
            continue
        seen.add(code)
        options.append(PaymentMethodOption(code=code, label=label))
    if options:
        return options
    if not _fallback:
        return []
    return parse_payment_methods(DEFAULT_PAYMENT_METHODS, _fallback=False)
