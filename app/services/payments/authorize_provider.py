"""Proveedor Authorize.net — stub hasta configurar credenciales."""

from decimal import Decimal

from app.core.config import Settings


class AuthorizePaymentProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return self.settings.authorize_configured

    def create_checkout_link(
        self,
        *,
        amount: Decimal,
        currency: str,
        customer_email: str,
        description: str | None,
        return_url: str,
        cancel_url: str,
    ) -> tuple[str | None, str | None]:
        """Retorna (external_id, checkout_url). Stub devuelve (None, None)."""
        if not self.is_configured:
            return None, None
        # TODO: integrar Accept Hosted / Payment Links de Authorize.net
        raise NotImplementedError("Authorize.net checkout pendiente de integración")
