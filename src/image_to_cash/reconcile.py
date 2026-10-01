"""Cross-check critical reader fields against an independent OCR read (design §4, step 4).

A field counts as confirmed only when its printed form appears inside one OCR box, as whole
tokens, and the page shows it at least as many times as there are fields claiming it. A
match never spans two boxes, so neighbouring boxes cannot be glued into a value.

Limits: the check ignores where a value sits, so two fields that swapped values (say billing
and delivery ZIP) both pass; catching that needs box geometry. A thousands group printed with
a space ("1 250.00") still contains "250.00" as whole tokens. Space is not accepted as a
thousands separator, so "2 250.00" (a quantity beside a price) never confirms 2250.00.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from image_to_cash.model import Order
from image_to_cash.ocr.base import TextBox

# Folded on both sides: OCR confuses these, and "," -> "." also unifies decimal commas.
LOOKALIKES = str.maketrans({"O": "0", "I": "1", "L": "1", ",": "."})
DASHES = str.maketrans(dict.fromkeys("‐‑‒–—−", "-"))
AMOUNT = re.compile(r"\d+\.\d\d")
THOUSANDS_SEPARATOR = r"[.']?"
# Alphanumeric runs stay intact; OCR may add or drop spaces between runs and punctuation.
TOKEN_PIECE = re.compile(r"[^\W_]+|\S")


@dataclass(frozen=True)
class Mismatch:
    field: str
    expected: str


def fold(text: str) -> str:
    """Uppercase, drop accents, unify dashes and lookalikes, collapse whitespace to one space."""
    decomposed = unicodedata.normalize("NFKD", text.upper())
    bare = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(bare.translate(DASHES).translate(LOOKALIKES).split())


def value_pattern(expected: str) -> re.Pattern[str]:
    """Matches the printed value as whole tokens inside one folded OCR line."""
    folded = fold(expected)
    body = _amount_body(folded) if AMOUNT.fullmatch(folded) else _text_body(folded)
    # Decided before folding, so a value of lookalike letters only ("OIL") keeps letter edges.
    edge = r"\w" if any(char.isalpha() for char in expected) else "[0-9]"
    head = f"(?<!{edge})" + (r"(?<![0-9][.])" if folded[0].isdigit() else "")
    tail = f"(?!{edge})" if folded[-1].isalnum() else ""
    return re.compile(head + body + tail)


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
    lines = tuple(fold(box.text) for box in text_boxes)
    fields = critical_fields(order)
    patterns = tuple(value_pattern(expected) for _, expected in fields)
    return tuple(
        Mismatch(field, expected)
        for index, (field, expected) in enumerate(fields)
        if _claim_rank(patterns, index) > _occurrences(patterns[index], lines)
    )


def _amount_body(amount: str) -> str:
    """'1250.00' -> 1[.']?250\\.00, because a printed amount may group its thousands."""
    whole, cents = amount.split(".")
    groups = [whole[max(0, end - 3) : end] for end in range(len(whole), 0, -3)][::-1]
    return THOUSANDS_SEPARATOR.join(groups) + r"\." + cents


def _text_body(value: str) -> str:
    return r"\s*".join(re.escape(piece) for piece in TOKEN_PIECE.findall(value))


def _claim_rank(patterns: tuple[re.Pattern[str], ...], index: int) -> int:
    """1 for the first field claiming this value, 2 for the second, and so on."""
    return sum(1 for pattern in patterns[: index + 1] if pattern.pattern == patterns[index].pattern)


def _occurrences(pattern: re.Pattern[str], lines: tuple[str, ...]) -> int:
    return sum(len(pattern.findall(line)) for line in lines)


def _amount(value: Decimal) -> str:
    return f"{value:.2f}"


def _percent(value: Decimal) -> str:
    return f"{value.normalize():f}%"
