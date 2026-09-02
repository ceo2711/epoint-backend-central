from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.services.payments.amounts import STANDARD_INITIAL_PAYMENT


PaymentProviderLiteral = Literal["authorize", "paypal", "stripe"]
PaymentLinkStatusLiteral = Literal["pending", "partial", "paid", "expired", "cancelled"]
DEFAULT_PAYMENT_AMOUNT = STANDARD_INITIAL_PAYMENT


class PaymentProviderStatus(BaseModel):
    provider: PaymentProviderLiteral
    configured: bool
    label: str


class PaymentConfigResponse(BaseModel):
    payments_enabled: bool
    default_provider: PaymentProviderLiteral
    stub_mode: bool
    payment_test: bool = False
    providers: list[PaymentProviderStatus]
    webhook_base_url: str | None = None


class PaymentConfigUpdate(BaseModel):
    payments_enabled: bool | None = None
    default_provider: PaymentProviderLiteral | None = None


class PaymentLinkCreate(BaseModel):
    customer_first_name: str = Field(min_length=1, max_length=100)
    customer_last_name: str = Field(min_length=1, max_length=100)
    customer_email: EmailStr
    customer_phone: str = Field(min_length=5, max_length=30)
    amount: Decimal = Field(default=DEFAULT_PAYMENT_AMOUNT, gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    provider: PaymentProviderLiteral
    description: str | None = Field(default=None, max_length=2000)
    prospect_id: int | None = None
    send_email: bool = True
    allow_partial: bool = False
    remainder_due_on: date | None = None

    @model_validator(mode="after")
    def remainder_due_required_for_partial(self):
        if self.allow_partial:
            if self.remainder_due_on is None:
                raise ValueError("Indicá la fecha acordada para completar el saldo")
            if self.remainder_due_on < datetime.now(timezone.utc).date() - timedelta(days=1):
                raise ValueError("La fecha para completar el saldo no puede ser anterior a hoy")
        return self


class PaymentLinkResponse(BaseModel):
    id: int
    public_token: str
    created_by_user_id: int
    client_id: int | None
    prospect_id: int | None = None
    customer_first_name: str
    customer_last_name: str
    customer_email: str
    customer_phone: str
    amount: Decimal
    amount_paid: Decimal = Decimal("0.00")
    remaining_amount: Decimal | None = None
    allow_partial: bool = False
    currency: str
    provider: PaymentProviderLiteral
    status: PaymentLinkStatusLiteral
    description: str | None
    payment_url: str
    external_checkout_url: str | None
    paid_at: datetime | None
    remainder_due_on: date | None = None
    client_registered_at: datetime | None
    created_at: datetime
    created_by_name: str | None = None

    model_config = {"from_attributes": True}


class PaymentLinkCreateResponse(BaseModel):
    link: PaymentLinkResponse
    message: str
    email_sent: bool = False


class PublicPaymentLinkResponse(BaseModel):
    customer_first_name: str
    customer_last_name: str
    customer_email: str
    amount: Decimal
    amount_paid: Decimal = Decimal("0.00")
    remaining_amount: Decimal
    allow_partial: bool = False
    currency: str
    provider: PaymentProviderLiteral
    status: PaymentLinkStatusLiteral
    description: str | None
    stub_mode: bool
    payment_test: bool = False
    can_pay: bool
    checkout_url: str | None = None
    hosted_payment_token: str | None = None
    provider_label: str | None = None


class PublicPaymentAmountRequest(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class PaymentRegisterClientRequest(BaseModel):
    merchant_id: int
    source: str = "OTHER"


class PaymentRegisterClientResponse(BaseModel):
    client_id: int
    message: str
