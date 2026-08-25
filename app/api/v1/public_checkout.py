from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession
from app.core.config import get_settings
from app.models.enums import EDUCATION_PRODUCT_CODES
from app.schemas.entitlements import (
    CatalogProductPublic,
    PublicCheckoutRequest,
    PublicCheckoutResponse,
)
from app.schemas.payment import PaymentLinkCreate
from app.services.entitlements import EntitlementService
from app.services.payments.service import PaymentService

router = APIRouter(prefix="/public", tags=["Checkout público"])


@router.get("/products", response_model=list[CatalogProductPublic])
def list_public_products(db: DbSession) -> list[CatalogProductPublic]:
    from sqlalchemy import select

    from app.models.catalog_product import CatalogProduct

    rows = db.execute(
        select(CatalogProduct).where(
            CatalogProduct.is_active.is_(True),
            CatalogProduct.code.in_(tuple(EDUCATION_PRODUCT_CODES)),
        )
    ).scalars().all()
    return [CatalogProductPublic.model_validate(row) for row in rows]


@router.post("/checkout", response_model=PublicCheckoutResponse)
def public_checkout(payload: PublicCheckoutRequest, db: DbSession) -> PublicCheckoutResponse:
    code = payload.product_code.strip().upper()
    if code not in EDUCATION_PRODUCT_CODES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Producto inválido")

    entitlements = EntitlementService(db)
    product = entitlements.get_active_product(code)
    merchant = entitlements.education_merchant()
    actor = entitlements.system_actor()

    settings = get_settings()
    provider = (payload.provider or settings.payments_default_provider_normalized).lower()
    if provider not in ("authorize", "paypal"):
        provider = "authorize"

    payments = PaymentService(db)
    result = payments.create_link(
        actor,
        PaymentLinkCreate(
            customer_first_name=payload.first_name.strip(),
            customer_last_name=payload.last_name.strip(),
            customer_email=payload.email,
            customer_phone=payload.phone.strip(),
            amount=product.amount,
            currency=product.currency or "USD",
            provider=provider,  # type: ignore[arg-type]
            description=product.name,
            send_email=False,
        ),
        merchant_id=merchant.id,
        product_code=code,
        skip_access_check=True,
    )
    return PublicCheckoutResponse(
        payment_url=result.link.payment_url,
        public_token=result.link.public_token,
        amount=float(result.link.amount),
        currency=result.link.currency,
        product_code=code,
        product_name=product.name,
    )
