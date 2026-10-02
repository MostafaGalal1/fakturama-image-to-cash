"""Stage-1 data contract: what was printed on the order image (frozen, validated)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Bounded types: a garbled reading (e.g. "1E+30") must fail validation, not crash the money maths.
NonEmptyStr = Annotated[str, Field(min_length=1)]
Amount = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=4)]
Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]


class PaymentMethod(StrEnum):
    BANK_TRANSFER = "Bank Transfer"
    CREDIT_CARD = "Credit Card"
    SEPA_DIRECT_DEBIT = "SEPA Direct Debit"


class PaidStatus(StrEnum):
    PAID = "PAID"
    UNPAID = "UNPAID"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class Address(Frozen):
    name: NonEmptyStr
    street: NonEmptyStr
    zip: NonEmptyStr
    city: NonEmptyStr
    country: NonEmptyStr


class Customer(Frozen):
    customer_id: str | None = None
    company: NonEmptyStr
    alias: NonEmptyStr
    contact_name: NonEmptyStr
    email: str = Field(min_length=3)
    phone: NonEmptyStr


class LineItem(Frozen):
    sku: NonEmptyStr
    description: NonEmptyStr
    quantity: Quantity
    unit: NonEmptyStr
    unit_net_price: Amount
    discount_percent: Percent
    vat_percent: Percent
    line_net_total: Amount


class Payment(Frozen):
    method: PaymentMethod
    status: PaidStatus
    payment_date: date | None = None


class Totals(Frozen):
    net: Amount
    vat: Amount
    gross: Amount


class Order(Frozen):
    external_reference: NonEmptyStr
    order_date: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    customer: Customer
    billing_address: Address
    delivery_address: Address
    payment: Payment
    items: tuple[LineItem, ...] = Field(min_length=1)
    totals: Totals
