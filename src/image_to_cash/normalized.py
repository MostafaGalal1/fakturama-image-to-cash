"""Stage-2 contract: the extracted order mapped onto what Fakturama needs (design §4, step 6)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import Field

from image_to_cash.errors import NeedsReview
from image_to_cash.invariants import HUNDRED, money
from image_to_cash.model import Address, Frozen, LineItem, Order, Payment, PaymentMethod, Totals


class Debtor(Frozen):
    company: str
    first_name: str
    last_name: str
    alias: str
    email: str
    phone: str
    billing_address: Address
    delivery_address: Address
    delivery_differs: bool
    payment_method: PaymentMethod


class Product(Frozen):
    sku: str
    name: str
    description: str
    gross_price: Decimal
    vat_percent: Decimal


class OrderLine(Frozen):
    sku: str
    quantity: Decimal
    unit_net_price: Decimal
    discount_percent: Decimal
    vat_percent: Decimal
    line_net_total: Decimal


class NormalizedOrder(Frozen):
    external_reference: str
    order_date: date
    source_customer_id: str | None
    debtor: Debtor
    products: tuple[Product, ...] = Field(min_length=1)
    lines: tuple[OrderLine, ...] = Field(min_length=1)
    payment: Payment
    totals: Totals


def split_contact_name(full_name: str) -> tuple[str, str]:
    parts = full_name.split()
    if len(parts) != 2:
        raise NeedsReview("contact_name_ambiguous", {"contact_name": full_name})
    return parts[0], parts[1]


def gross_price(net: Decimal, vat_percent: Decimal) -> Decimal:
    return money(net * (1 + vat_percent / HUNDRED))


def normalize(order: Order) -> NormalizedOrder:
    first_name, last_name = split_contact_name(order.customer.contact_name)
    return NormalizedOrder(
        external_reference=order.external_reference,
        order_date=order.order_date,
        source_customer_id=order.customer.customer_id,
        debtor=Debtor(
            company=order.customer.company,
            first_name=first_name,
            last_name=last_name,
            alias=order.customer.alias,
            email=order.customer.email,
            phone=order.customer.phone,
            billing_address=order.billing_address,
            delivery_address=order.delivery_address,
            delivery_differs=order.billing_address != order.delivery_address,
            payment_method=order.payment.method,
        ),
        products=_products(order.items),
        lines=tuple(_line(item) for item in order.items),
        payment=order.payment,
        totals=order.totals,
    )


def _products(items: tuple[LineItem, ...]) -> tuple[Product, ...]:
    by_sku: dict[str, Product] = {}
    for item in items:
        product = Product(
            sku=item.sku,
            name=item.description,
            description=item.description,
            gross_price=gross_price(item.unit_net_price, item.vat_percent),
            vat_percent=item.vat_percent,
        )
        existing = by_sku.get(item.sku)
        if existing is not None and existing != product:
            raise NeedsReview("conflicting_sku_lines", {"sku": item.sku})
        by_sku = {**by_sku, item.sku: product}
    return tuple(by_sku.values())


def _line(item: LineItem) -> OrderLine:
    return OrderLine(
        sku=item.sku,
        quantity=item.quantity,
        unit_net_price=item.unit_net_price,
        discount_percent=item.discount_percent,
        vat_percent=item.vat_percent,
        line_net_total=item.line_net_total,
    )
