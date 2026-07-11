"""Proveedor Stripe — stub hasta configurar credenciales."""

from decimal import Decimal

from app.core.config import Settings


class StripePaymentProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return self.settings.stripe_configured

    def create_checkout_link(
        self,
        *,
        amount: Decimal,
        currency: str,
        customer_email: str,
        description: str | None,
        success_url: str,
        cancel_url: str,
    ) -> tuple[str | None, str | None]:
        """Retorna (external_id, checkout_url). Stub devuelve (None, None)."""
        if not self.is_configured:
            return None, None
        # TODO: integrar stripe.checkout.Session.create cuando haya credenciales
        raise NotImplementedError("Stripe checkout pendiente de integración")
