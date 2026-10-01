"""Arithmetic and business invariants on an extracted Order (design §4, step 5)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from image_to_cash.model import LineItem, Order, PaidStatus

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
SUPPORTED_CURRENCY = "EUR"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Issue:
    code: str
    message: str


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def expected_line_net(
    quantity: Decimal, unit_net_price: Decimal, discount_percent: Decimal
) -> Decimal:
    return money(quantity * unit_net_price * (1 - discount_percent / HUNDRED))


def check_invariants(order: Order) -> tuple[Issue, ...]:
    return (
        *_line_issues(order),
        *_total_issues(order),
        *_payment_issues(order),
        *_currency_issues(order),
        *_contact_issues(order),
    )


def _line_issues(order: Order) -> tuple[Issue, ...]:
    checked = (_check_line(index, item) for index, item in enumerate(order.items, start=1))
    return tuple(issue for issue in checked if issue is not None)


def _check_line(index: int, item: LineItem) -> Issue | None:
    expected = expected_line_net(item.quantity, item.unit_net_price, item.discount_percent)
    if expected == money(item.line_net_total):
        return None
    return Issue(
        "line_net_mismatch",
        f"line {index} ({item.sku}): expected {expected}, printed {item.line_net_total}",
    )


def _total_issues(order: Order) -> tuple[Issue, ...]:
    net = money(sum((item.line_net_total for item in order.items), Decimal(0)))
    vat = money(
        sum((item.line_net_total * item.vat_percent / HUNDRED for item in order.items), Decimal(0))
    )
    checks = (
        ("net_total_mismatch", net, order.totals.net),
        ("vat_total_mismatch", vat, order.totals.vat),
        ("gross_total_mismatch", money(order.totals.net + order.totals.vat), order.totals.gross),
    )
    return tuple(
        Issue(code, f"expected {expected}, printed {printed}")
        for code, expected, printed in checks
        if expected != money(printed)
    )


def _payment_issues(order: Order) -> tuple[Issue, ...]:
    paid = order.payment.status is PaidStatus.PAID
    has_date = order.payment.payment_date is not None
    if paid and not has_date:
        return (Issue("paid_without_date", "status is PAID but no payment date was printed"),)
    if not paid and has_date:
        return (Issue("unpaid_with_date", "status is not PAID but a payment date was printed"),)
    return ()


def _currency_issues(order: Order) -> tuple[Issue, ...]:
    if order.currency == SUPPORTED_CURRENCY:
        return ()
    return (
        Issue("unsupported_currency", f"only {SUPPORTED_CURRENCY} is supported, got {order.currency}"),
    )


def _contact_issues(order: Order) -> tuple[Issue, ...]:
    if EMAIL_PATTERN.match(order.customer.email):
        return ()
    return (Issue("invalid_email", f"not an email address: {order.customer.email}"),)
