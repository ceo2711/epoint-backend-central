"""Proveedor Authorize.net — Accept Hosted (página de pago hospedada)."""

from __future__ import annotations

import json
import logging
from decimal import Decimal

import httpx

from app.core.config import Settings
from app.services.payments.base import PaymentCheckoutResult, PaymentProviderError

logger = logging.getLogger(__name__)


class AuthorizePaymentProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return self.settings.authorize_configured

    @property
    def api_base(self) -> str:
        if self.settings.authorize_environment_normalized == "production":
            return "https://api.authorize.net/xml/v1/request.api"
        return "https://apitest.authorize.net/xml/v1/request.api"

    @property
    def hosted_base(self) -> str:
        if self.settings.authorize_environment_normalized == "production":
            return "https://accept.authorize.net/payment/payment"
        return "https://test.authorize.net/payment/payment"

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
            raise PaymentProviderError("Authorize.net no está configurado")

        amount_str = f"{amount.quantize(Decimal('0.01')):.2f}"
        payload = {
            "getHostedPaymentPageRequest": {
                "merchantAuthentication": {
                    "name": self.settings.authorize_api_login_id,
                    "transactionKey": self.settings.authorize_transaction_key,
                },
                "transactionRequest": {
                    "transactionType": "authCaptureTransaction",
                    "amount": amount_str,
                    "currencyCode": currency.upper(),
                    "order": {
                        "invoiceNumber": reference_id[:20],
                        "description": (description or "Pago ePoint CRM")[:255],
                    },
                    "billTo": {
                        "email": customer_email[:255],
                    },
                },
                "hostedPaymentSettings": {
                    "setting": [
                        {
                            "settingName": "hostedPaymentReturnOptions",
                            "settingValue": json.dumps(
                                {
                                    "showReceipt": True,
                                    "url": return_url,
                                    "urlText": "Continuar",
                                    "cancelUrl": cancel_url,
                                    "cancelUrlText": "Cancelar",
                                }
                            ),
                        },
                        {
                            "settingName": "hostedPaymentButtonOptions",
                            "settingValue": json.dumps({"text": "Pagar"}),
                        },
                    ]
                },
            }
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(self.api_base, json=payload)

        if response.status_code >= 400:
            logger.warning("Authorize.net hosted page error: %s", response.text[:500])
            raise PaymentProviderError(
                f"No se pudo crear la página de pago Authorize.net ({response.status_code})",
                status_code=response.status_code,
            )

        data = response.json()
        token_response = data.get("token") or data.get("getHostedPaymentPageResponse", {}).get("token")
        if not token_response:
            messages = data.get("messages") or data.get("getHostedPaymentPageResponse", {}).get("messages")
            detail = str(messages) if messages else response.text[:200]
            raise PaymentProviderError(f"Authorize.net no devolvió token: {detail}")

        checkout_url = f"{self.hosted_base}?token={token_response}"
        return PaymentCheckoutResult(external_id=str(token_response), checkout_url=checkout_url)
