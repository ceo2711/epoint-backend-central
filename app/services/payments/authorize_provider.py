"""Proveedor Authorize.net — Accept Hosted (página de pago hospedada)."""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal

import httpx

from app.core.config import Settings
from app.services.payments.base import PaymentCheckoutResult, PaymentProviderError

logger = logging.getLogger(__name__)


def _authorize_safe_url(url: str) -> str:
    """Authorize.net sandbox rechaza 'localhost' en return/cancel; 127.0.0.1 sí pasa.

    También evita '&' en return/cancel (rompe Accept Hosted).
    """
    safe = (
        url.replace("://localhost:", "://127.0.0.1:")
        .replace("://localhost/", "://127.0.0.1/")
    )
    # Accept Hosted falla si return/cancel traen '&' (query extra).
    if "?" in safe:
        base, _, query = safe.partition("?")
        # Un solo query param sin '&' está OK (ej. ?paid=1).
        if "&" in query:
            return base
    return safe


def _digits_phone(value: str) -> str:
    return re.sub(r"\D+", "", value or "")[:25]


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
        customer_first_name: str = "",
        customer_last_name: str = "",
        customer_phone: str = "",
    ) -> PaymentCheckoutResult:
        if not self.is_configured:
            raise PaymentProviderError("Authorize.net no está configurado")

        amount_str = f"{amount.quantize(Decimal('0.01')):.2f}"
        return_url = _authorize_safe_url(return_url)
        cancel_url = _authorize_safe_url(cancel_url)

        bill_to: dict[str, str] = {}
        email = customer_email.strip()
        first = customer_first_name.strip()[:50]
        last = customer_last_name.strip()[:50]
        phone = _digits_phone(customer_phone)
        # billTo no admite email (va en customer.email).
        if first:
            bill_to["firstName"] = first
        if last:
            bill_to["lastName"] = last
        if phone:
            bill_to["phoneNumber"] = phone

        merchant_name = (self.settings.app_name or "ePoint").replace(" API", "").strip()[:35] or "ePoint"

        transaction_request: dict = {
            "transactionType": "authCaptureTransaction",
            "amount": amount_str,
            "currencyCode": currency.upper(),
            "order": {
                "invoiceNumber": reference_id[:20],
                "description": (description or f"Pago {merchant_name}")[:255],
            },
        }
        if email:
            transaction_request["customer"] = {"email": email[:255]}
        if bill_to:
            transaction_request["billTo"] = bill_to

        payload = {
            "getHostedPaymentPageRequest": {
                "merchantAuthentication": {
                    "name": self.settings.authorize_api_login_id,
                    "transactionKey": self.settings.authorize_transaction_key,
                },
                "transactionRequest": transaction_request,
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
                        {
                            "settingName": "hostedPaymentOrderOptions",
                            "settingValue": json.dumps(
                                {"show": True, "merchantName": merchant_name}
                            ),
                        },
                        {
                            # Color de acento (Accept Hosted no permite subir logo).
                            "settingName": "hostedPaymentStyleOptions",
                            "settingValue": json.dumps({"bgColor": "#3d6b45"}),
                        },
                        {
                            "settingName": "hostedPaymentPaymentOptions",
                            "settingValue": json.dumps(
                                {
                                    "cardCodeRequired": True,
                                    "showCreditCard": True,
                                    "showBankAccount": False,
                                }
                            ),
                        },
                        {
                            "settingName": "hostedPaymentBillingAddressOptions",
                            "settingValue": json.dumps({"show": True, "required": False}),
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

        # Accept Hosted requiere POST del token (GET con query string falla: "Missing or invalid token").
        token = str(token_response)
        return PaymentCheckoutResult(external_id=token, checkout_url=self.hosted_base)
