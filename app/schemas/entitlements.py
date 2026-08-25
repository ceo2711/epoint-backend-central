from pydantic import BaseModel, EmailStr, Field

from app.models.enums import ProductCode


class EntitlementsResponse(BaseModel):
    credit: bool = False
    course: bool = False
    mentorship: bool = False


class CatalogProductPublic(BaseModel):
    code: str
    name: str
    description: str | None
    amount: float
    currency: str

    model_config = {"from_attributes": True}


class PublicCheckoutRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=5, max_length=30)
    product_code: str = Field(min_length=1, max_length=40)
    provider: str | None = None


class PublicCheckoutResponse(BaseModel):
    payment_url: str
    public_token: str
    amount: float
    currency: str
    product_code: str
    product_name: str


def entitlements_from_codes(codes: set[str]) -> EntitlementsResponse:
    return EntitlementsResponse(
        credit=ProductCode.CREDIT.value in codes,
        course=ProductCode.COURSE.value in codes,
        mentorship=ProductCode.MENTORSHIP.value in codes,
    )
