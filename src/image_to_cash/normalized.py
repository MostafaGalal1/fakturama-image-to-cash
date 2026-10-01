"""Stage-2 contract: the extracted order mapped onto what Fakturama needs (design §4, step 6).

Precondition: callers run `check_invariants` first; `normalize` does no arithmetic checking.
The contract is re-validated whenever order.json is loaded, because a person may have edited it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import Field, model_validator

from image_to_cash.errors import NeedsReview
from image_to_cash.invariants import HUNDRED, money
from image_to_cash.model import (
    Address,
    Amount,
    Frozen,
    LineItem,
    NonEmptyStr,
    Order,
    Payment,
    Percent,
    Quantity,
    Totals,
)

# A gross price can exceed a net Amount's 12 digits (net × up to 2), so it gets one more digit.
GrossPrice = Annotated[Decimal, Field(ge=0, max_digits=13, decimal_places=2)]


class Debtor(Frozen):
    company: NonEmptyStr
    first_name: NonEmptyStr
    last_name: NonEmptyStr
    alias: NonEmptyStr
    email: NonEmptyStr
    phone: NonEmptyStr
    billing_address: Address
    delivery_address: Address

    @property
    def delivery_differs(self) -> bool:
        """Exact comparison of all fields, name line included: a false 'same' would misship."""
        return self.billing_address != self.delivery_address


class Product(Frozen):
    """Master data. Fakturama's Name and Description both get `description`.

    `gross_price` is net × (1 + VAT) and never includes a line discount.
    """

    sku: NonEmptyStr
    description: NonEmptyStr
    gross_price: GrossPrice
    vat_percent: Percent


class OrderLine(Frozen):
    """One Order line as typed into Fakturama: U.Price is the net unit price."""

    sku: NonEmptyStr
    quantity: Quantity
    unit_net_price: Amount
    discount_percent: Percent
    vat_percent: Percent
    line_net_total: Amount


class NormalizedOrder(Frozen):
    external_reference: NonEmptyStr
    order_date: date
    source_customer_id: str | None  # recorded only; Fakturama proposes its own Customer ID
    debtor: Debtor
    products: tuple[Product, ...] = Field(min_length=1)
    lines: tuple[OrderLine, ...] = Field(min_length=1)
    payment: Payment
    totals: Totals

    @model_validator(mode="after")
    def _lines_match_products(self) -> NormalizedOrder:
        vat_by_sku = {product.sku: product.vat_percent for product in self.products}
        if len(vat_by_sku) != len(self.products):
            raise ValueError("product SKUs must be unique")
        for line in self.lines:
            if line.sku not in vat_by_sku:
                raise ValueError(f"line SKU {line.sku} has no product")
            if line.vat_percent != vat_by_sku[line.sku]:
                raise ValueError(f"line SKU {line.sku} has a different VAT than its product")
        return self


def split_contact_name(full_name: str) -> tuple[str, str]:
    """Accept 'First Last', or 'Last, First Names' (how a reviewer writes multi-word names)."""
    if "," in full_name:
        last, _, first = full_name.partition(",")
        last, first = last.strip(), first.strip()
        if last and first and "," not in first:
            return first, last
        raise _ambiguous_name(full_name)
    parts = full_name.split()
    if len(parts) == 2 and not any(part.endswith(".") for part in parts):
        return parts[0], parts[1]
    raise _ambiguous_name(full_name)


def gross_price(net: Decimal, vat_percent: Decimal) -> Decimal:
    return money(net * (1 + vat_percent / HUNDRED))


def normalize(order: Order) -> NormalizedOrder:
    customer = order.customer
    first_name, last_name = split_contact_name(customer.contact_name)
    return NormalizedOrder(
        external_reference=order.external_reference,
        order_date=order.order_date,
        source_customer_id=customer.customer_id,
        debtor=Debtor(
            company=customer.company,
            first_name=first_name,
            last_name=last_name,
            alias=customer.alias,
            email=customer.email,
            phone=customer.phone,
            billing_address=order.billing_address,
            delivery_address=order.delivery_address,
        ),
        products=_products(order.items),
        lines=tuple(_line(item) for item in order.items),
        payment=order.payment,
        totals=order.totals,
    )


def _ambiguous_name(full_name: str) -> NeedsReview:
    return NeedsReview("contact_name_ambiguous", {"contact_name": full_name})


def _products(items: tuple[LineItem, ...]) -> tuple[Product, ...]:
    by_sku: dict[str, Product] = {}
    for item in items:
        product = _product(item)
        if by_sku.setdefault(item.sku, product) != product:
            raise NeedsReview("conflicting_sku_lines", {"sku": item.sku})
    return tuple(by_sku.values())


def _product(item: LineItem) -> Product:
    return Product(
        sku=item.sku,
        description=item.description,
        gross_price=gross_price(item.unit_net_price, item.vat_percent),
        vat_percent=item.vat_percent,
    )


def _line(item: LineItem) -> OrderLine:
    return OrderLine(
        sku=item.sku,
        quantity=item.quantity,
        unit_net_price=item.unit_net_price,
        discount_percent=item.discount_percent,
        vat_percent=item.vat_percent,
        line_net_total=item.line_net_total,
    )
