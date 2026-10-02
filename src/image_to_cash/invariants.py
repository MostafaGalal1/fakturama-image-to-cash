"""Arithmetic and business invariants on an extracted Order (design §4, step 5)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from image_to_cash.model import LineItem, Order, PaidStatus

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
SUPPORTED_CURRENCY = "EUR"
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@dataclass(frozen=True)
class Issue:
    code: str
    message: str


def money(value: Decimal) -> Decimal:
    """Round a Decimal to cents, half-up (never the context's default banker's rounding)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def expected_line_net(
    quantity: Decimal, unit_net_price: Decimal, discount_percent: Decimal
) -> Decimal:
    """qty × unit × (1 − discount/100), rounded once at the end (no rounding of the unit price)."""
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
        f"line {index} ({item.sku}): {item.quantity} × {item.unit_net_price:.2f} "
        f"− {item.discount_percent}% is {expected:.2f}, printed {money(item.line_net_total):.2f}",
    )


def _sum_line_nets(order: Order) -> Decimal:
    return money(sum((item.line_net_total for item in order.items), Decimal(0)))


def vat_total(lines: Iterable[tuple[Decimal, Decimal]]) -> Decimal:
    """Convention: Σ(printed line net × VAT%) over (net, VAT%) pairs, rounded once at the end.

    A document that rounds VAT per line can differ by a cent; it goes to review, never silently through.
    """
    return money(sum((net * percent / HUNDRED for net, percent in lines), Decimal(0)))


def _expected_vat(order: Order) -> Decimal:
    return vat_total((item.line_net_total, item.vat_percent) for item in order.items)


def _total_issues(order: Order) -> tuple[Issue, ...]:
    checks = (
        ("net_total_mismatch", "net total: printed line nets sum to", _sum_line_nets(order), order.totals.net),
        ("vat_total_mismatch", "VAT total: Σ(line net × VAT%) is", _expected_vat(order), order.totals.vat),
        (
            "gross_total_mismatch",
            "gross total: printed net + VAT is",
            money(order.totals.net + order.totals.vat),
            order.totals.gross,
        ),
    )
    return tuple(
        Issue(code, f"{label} {expected:.2f}, printed total is {money(printed):.2f}")
        for code, label, expected, printed in checks
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
    if EMAIL_PATTERN.fullmatch(order.customer.email):
        return ()
    return (Issue("invalid_email", f"not an email address: {order.customer.email}"),)
