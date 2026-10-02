"""What Fakturama puts on the clipboard when rows of a grid are copied, as typed records.

The copy holds the stored values, not the display text: a VAT rate is a fraction (0.19), a line
discount is a negative fraction (-0.1 for 10 %), a price is "EUR 250", a VAT cell is the Java
object's toString, and an empty cell is "null". Every parser checks the column count, so a
changed grid layout fails loudly instead of shifting values into the wrong fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from image_to_cash.drive.grid import parse_rows

HUNDRED = Decimal(100)
CURRENCY_PREFIX = "EUR "
NULL = "null"
_VAT_RATE = re.compile(r"taxValue: \[(-?[0-9.]+)\]")
_VAT_NAME = re.compile(r"\bname: \[([^\]]*)\]")


class DocumentState(StrEnum):
    OPEN = "COMMAND_ORDER_PENDING"  # shown as "open"
    PAID = "COMMAND_CHECKED"  # shown as "paid"
    UNPAID = "COMMAND_UNPAID"


@dataclass(frozen=True)
class VatRow:
    standard: bool
    name: str
    description: str
    percent: Decimal


@dataclass(frozen=True)
class PaymentRow:
    standard: bool
    name: str
    description: str
    discount_percent: Decimal
    discount_days: int
    net_days: int


@dataclass(frozen=True)
class AddressRow:
    customer_id: str
    first_name: str
    last_name: str
    company: str
    zip: str
    city: str
    address_type: str


@dataclass(frozen=True)
class ProductRow:
    sku: str
    name: str
    description: str
    gross_price: Decimal
    vat_name: str
    vat_percent: Decimal


@dataclass(frozen=True)
class LineRow:
    quantity: Decimal
    sku: str
    name: str
    vat_percent: Decimal
    unit_net_price: Decimal
    discount_percent: Decimal
    line_net_total: Decimal


@dataclass(frozen=True)
class DocumentRow:
    kind: str  # ORDER, INVOICE, ...
    number: str
    date: date
    name: str
    reference: str
    state: DocumentState | str  # an unknown state stays raw, for the report
    total: Decimal


def parse_vat_rows(copied: str) -> tuple[VatRow, ...]:
    return tuple(
        VatRow(_flag(standard), name, description, _number(rate) * HUNDRED)
        for standard, name, description, rate in _rows(copied, 4, "VAT list")
    )


def parse_payment_rows(copied: str) -> tuple[PaymentRow, ...]:
    return tuple(
        PaymentRow(_flag(standard), name, description, _number(discount) * HUNDRED, int(days), int(net))
        for standard, name, description, discount, days, net in _rows(copied, 6, "terms of payment list")
    )


def parse_address_rows(copied: str) -> tuple[AddressRow, ...]:
    return tuple(
        AddressRow(*(_text(cell) for cell in row[:7])) for row in _rows(copied, 9, "address selector")
    )


def parse_product_rows(copied: str) -> tuple[ProductRow, ...]:
    return tuple(
        ProductRow(sku, _text(name), _text(description), _number(price), *_vat(vat))
        for sku, name, description, _stock, price, vat in _rows(copied, 6, "product selector")
    )


def parse_line_rows(copied: str) -> tuple[LineRow, ...]:
    return tuple(
        LineRow(
            quantity=_number(quantity),
            sku=_text(sku),
            name=_text(name),
            vat_percent=_vat(vat)[1],
            unit_net_price=_money(unit_price),
            discount_percent=-_number(discount) * HUNDRED + 0,  # + 0 turns -0 into 0
            line_net_total=_money(price),
        )
        for quantity, sku, _picture, name, _description, vat, unit_price, discount, price in _rows(
            copied, 9, "order items"
        )
    )


def parse_document_rows(copied: str) -> tuple[DocumentRow, ...]:
    return tuple(
        DocumentRow(
            kind=icon.removeprefix("ICON_"),
            number=number,
            date=_java_date(when),
            name=_text(name),
            reference=_text(reference),
            state=_state(state),
            total=_number(total),
        )
        for icon, number, when, name, reference, state, total, _printed in _rows(copied, 8, "documents list")
    )


def _rows(copied: str, columns: int, grid: str) -> tuple[tuple[str, ...], ...]:
    rows = parse_rows(copied)
    for row in rows:
        if len(row) != columns:
            raise ValueError(f"{grid}: expected {columns} columns, got {len(row)}")
    return rows


def _text(cell: str) -> str:
    return "" if cell == NULL else cell


def _flag(cell: str) -> bool:
    if cell not in ("true", "false"):
        raise ValueError(f"not a flag: {cell!r}")
    return cell == "true"


def _number(cell: str) -> Decimal:
    try:
        return Decimal(cell)
    except InvalidOperation:
        raise ValueError(f"not a number: {cell!r}") from None


def _money(cell: str) -> Decimal:
    if not cell.startswith(CURRENCY_PREFIX):
        raise ValueError(f"not an EUR amount: {cell!r}")
    return _number(cell.removeprefix(CURRENCY_PREFIX))


def _vat(cell: str) -> tuple[str, Decimal]:
    rate, name = _VAT_RATE.search(cell), _VAT_NAME.search(cell)
    if rate is None or name is None:
        raise ValueError(f"VAT cell without a name and rate: {cell[:60]!r}")
    return name.group(1), _number(rate.group(1)) * HUNDRED


def _java_date(cell: str) -> date:
    """Java's Date.toString, e.g. 'Tue Jul 14 00:00:00 EEST 2026'; the zone name is ignored."""
    parts = cell.split()
    if len(parts) != 6:
        raise ValueError(f"not a Java date: {cell!r}")
    weekday, month, day, _time, _zone, year = parts
    return datetime.strptime(f"{weekday} {month} {day} {year}", "%a %b %d %Y").date()


def _state(cell: str) -> DocumentState | str:
    try:
        return DocumentState(cell)
    except ValueError:
        return cell
