from decimal import Decimal
from typing import Iterable

from app.models.payment_link import PaymentLink, PaymentLinkStatus

OPEN_PAYMENT_STATUSES = frozenset(
    {PaymentLinkStatus.PENDING.value, PaymentLinkStatus.PARTIAL.value}
)
SATISFIED_PAYMENT_STATUSES = frozenset(
    {PaymentLinkStatus.PAID.value, PaymentLinkStatus.PARTIAL.value}
)
STANDARD_INITIAL_PAYMENT = Decimal("3000.00")


def remaining_amount(link: PaymentLink) -> Decimal:
    paid = Decimal(link.amount_paid or 0)
    leftover = Decimal(link.amount) - paid
    return leftover if leftover > 0 else Decimal("0.00")


def is_open_payment(link: PaymentLink) -> bool:
    return link.status in OPEN_PAYMENT_STATUSES and remaining_amount(link) > 0


def is_payment_satisfied(link: PaymentLink) -> bool:
    if link.status in SATISFIED_PAYMENT_STATUSES:
        return True
    return Decimal(link.amount_paid or 0) > 0


def paid_total(links: Iterable[PaymentLink]) -> Decimal:
    return sum((Decimal(link.amount_paid or 0) for link in links), Decimal("0.00"))


def remaining_to_standard(links: Iterable[PaymentLink]) -> Decimal:
    leftover = STANDARD_INITIAL_PAYMENT - paid_total(links)
    return leftover if leftover > 0 else Decimal("0.00")


def is_standard_initial_complete(links: Iterable[PaymentLink]) -> bool:
    return paid_total(links) > 0 and remaining_to_standard(links) <= 0
