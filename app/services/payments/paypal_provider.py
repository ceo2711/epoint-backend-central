"""Proveedor PayPal Checkout (Orders API v2)."""

from __future__ import annotations

import logging
from decimal import Decimal

import httpx

from app.core.config import Settings
from app.services.payments.base import PaymentCheckoutResult, PaymentProviderError

logger = logging.getLogger(__name__)


class PayPalPaymentProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return self.settings.paypal_configured

    @property
    def api_base(self) -> str:
        if self.settings.paypal_environment_normalized == "production":
            return "https://api-m.paypal.com"
        return "https://api-m.sandbox.paypal.com"

    def _get_access_token(self, client: httpx.Client) -> str:
        response = client.post(
            f"{self.api_base}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(self.settings.paypal_client_id, self.settings.paypal_client_secret),
            headers={"Accept": "application/json"},
        )
        if response.status_code >= 400:
            raise PaymentProviderError(
                f"PayPal OAuth falló ({response.status_code})",
                status_code=response.status_code,
            )
        token = response.json().get("access_token")
        if not token:
            raise PaymentProviderError("PayPal OAuth no devolvió access_token")
        return str(token)

    def create_checkout_link(
        self,
        *,
        amount: Decimal,
        currency: str,
        customer_email: str,
        description: str | None,
        reference_id: str,
        return_url: str,
        cancel_url: str,
    ) -> PaymentCheckoutResult:
        if not self.is_configured:
            raise PaymentProviderError("PayPal no está configurado")

        amount_str = f"{amount.quantize(Decimal('0.01')):.2f}"
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": reference_id,
                    "custom_id": reference_id,
                    "description": (description or "Pago ePoint CRM")[:127],
                    "amount": {
                        "currency_code": currency.upper(),
                        "value": amount_str,
                    },
                }
            ],
            "application_context": {
                "brand_name": self.settings.app_name,
                "locale": "es-AR",
                "landing_page": "LOGIN",
                "user_action": "PAY_NOW",
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        }

        with httpx.Client(timeout=30.0) as client:
            access_token = self._get_access_token(client)
            response = client.post(
                f"{self.api_base}/v2/checkout/orders",
                json=payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )

        if response.status_code >= 400:
            logger.warning("PayPal create order error: %s", response.text[:500])
            raise PaymentProviderError(
                f"No se pudo crear la orden PayPal ({response.status_code})",
                status_code=response.status_code,
            )

        data = response.json()
        order_id = str(data.get("id", ""))
        approve_url = next(
            (link["href"] for link in data.get("links", []) if link.get("rel") == "approve"),
            None,
        )
        if not order_id or not approve_url:
            raise PaymentProviderError("Respuesta PayPal incompleta (sin order id o approve url)")

        return PaymentCheckoutResult(external_id=order_id, checkout_url=approve_url)

    def capture_order(self, order_id: str) -> dict:
        if not self.is_configured:
            raise PaymentProviderError("PayPal no está configurado")

        with httpx.Client(timeout=30.0) as client:
            access_token = self._get_access_token(client)
            response = client.post(
                f"{self.api_base}/v2/checkout/orders/{order_id}/capture",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )

        if response.status_code >= 400:
            raise PaymentProviderError(
                f"No se pudo capturar la orden PayPal ({response.status_code})",
                status_code=response.status_code,
            )
        return response.json()

    def get_order(self, order_id: str) -> dict:
        if not self.is_configured:
            raise PaymentProviderError("PayPal no está configurado")

        with httpx.Client(timeout=30.0) as client:
            access_token = self._get_access_token(client)
            response = client.get(
                f"{self.api_base}/v2/checkout/orders/{order_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if response.status_code >= 400:
            raise PaymentProviderError(
                f"No se pudo consultar la orden PayPal ({response.status_code})",
                status_code=response.status_code,
            )
        return response.json()
