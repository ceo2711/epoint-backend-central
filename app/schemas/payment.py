from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


PaymentProviderLiteral = Literal["stripe", "authorize"]
PaymentLinkStatusLiteral = Literal["pending", "paid", "expired", "cancelled"]


class PaymentProviderStatus(BaseModel):
    provider: PaymentProviderLiteral
    configured: bool
    label: str


class PaymentConfigResponse(BaseModel):
    payments_enabled: bool
    default_provider: PaymentProviderLiteral
    stub_mode: bool
    providers: list[PaymentProviderStatus]


class PaymentConfigUpdate(BaseModel):
    payments_enabled: bool | None = None
    default_provider: PaymentProviderLiteral | None = None


class PaymentLinkCreate(BaseModel):
    customer_first_name: str = Field(min_length=1, max_length=100)
    customer_last_name: str = Field(min_length=1, max_length=100)
    customer_email: EmailStr
    customer_phone: str = Field(min_length=5, max_length=30)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    provider: PaymentProviderLiteral
    description: str | None = Field(default=None, max_length=2000)


class PaymentLinkResponse(BaseModel):
    id: int
    public_token: str
    created_by_user_id: int
    client_id: int | None
    customer_first_name: str
    customer_last_name: str
    customer_email: str
    customer_phone: str
    amount: Decimal
    currency: str
    provider: PaymentProviderLiteral
    status: PaymentLinkStatusLiteral
    description: str | None
    payment_url: str
    external_checkout_url: str | None
    paid_at: datetime | None
    client_registered_at: datetime | None
    created_at: datetime
    created_by_name: str | None = None

    model_config = {"from_attributes": True}


class PaymentLinkCreateResponse(BaseModel):
    link: PaymentLinkResponse
    message: str


class PublicPaymentLinkResponse(BaseModel):
    customer_first_name: str
    customer_last_name: str
    customer_email: str
    amount: Decimal
    currency: str
    provider: PaymentProviderLiteral
    status: PaymentLinkStatusLiteral
    description: str | None
    stub_mode: bool
    can_pay: bool


class PaymentRegisterClientRequest(BaseModel):
    merchant_id: int
    source: str = "OTHER"


class PaymentRegisterClientResponse(BaseModel):
    client_id: int
    message: str
