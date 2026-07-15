"""Tipos compartidos entre proveedores de pago."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PaymentCheckoutResult:
    external_id: str
    checkout_url: str


class PaymentProviderError(Exception):
    """Error al comunicarse con un proveedor externo."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
