"""Cross-check critical reader fields against an independent OCR read (design §4, step 4)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from image_to_cash.model import Order
from image_to_cash.ocr.base import TextBox

LOOKALIKES = str.maketrans({"O": "0", "I": "1", "L": "1", ",": "."})


@dataclass(frozen=True)
class Mismatch:
    field: str
    expected: str


def normalize_token(text: str) -> str:
    return "".join(text.upper().split()).translate(LOOKALIKES)


def critical_fields(order: Order) -> tuple[tuple[str, str], ...]:
    header = (
        ("external_reference", order.external_reference),
        ("order_date", order.order_date.isoformat()),
        ("payment.status", order.payment.status.value),
        ("customer.phone", order.customer.phone),
        ("billing_address.street", order.billing_address.street),
        ("billing_address.zip", order.billing_address.zip),
        ("delivery_address.street", order.delivery_address.street),
        ("delivery_address.zip", order.delivery_address.zip),
        ("totals.net", _amount(order.totals.net)),
        ("totals.vat", _amount(order.totals.vat)),
        ("totals.gross", _amount(order.totals.gross)),
    )
    payment_date = order.payment.payment_date
    payment = (("payment.payment_date", payment_date.isoformat()),) if payment_date else ()
    items = tuple(
        pair
        for index, item in enumerate(order.items)
        for pair in (
            (f"items[{index}].sku", item.sku),
            (f"items[{index}].unit_net_price", _amount(item.unit_net_price)),
            (f"items[{index}].discount_percent", _percent(item.discount_percent)),
            (f"items[{index}].vat_percent", _percent(item.vat_percent)),
            (f"items[{index}].line_net_total", _amount(item.line_net_total)),
        )
    )
    return header + payment + items


def reconcile(order: Order, text_boxes: tuple[TextBox, ...]) -> tuple[Mismatch, ...]:
    haystack = normalize_token("".join(box.text for box in text_boxes))
    return tuple(
        Mismatch(field, expected)
        for field, expected in critical_fields(order)
        if normalize_token(expected) not in haystack
    )


def _amount(value: Decimal) -> str:
    return f"{value:.2f}"


def _percent(value: Decimal) -> str:
    return f"{value.normalize():f}%"
