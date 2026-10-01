"""Stage-1 data contract: what was printed on the order image (frozen, validated)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PaymentMethod(StrEnum):
    BANK_TRANSFER = "Bank Transfer"
    CREDIT_CARD = "Credit Card"
    SEPA_DIRECT_DEBIT = "SEPA Direct Debit"


class PaidStatus(StrEnum):
    PAID = "PAID"
    UNPAID = "UNPAID"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Address(Frozen):
    name: str = Field(min_length=1)
    street: str = Field(min_length=1)
    zip: str = Field(min_length=1)
    city: str = Field(min_length=1)
    country: str = Field(min_length=1)


class Customer(Frozen):
    customer_id: str | None = None
    company: str = Field(min_length=1)
    alias: str = Field(min_length=1)
    contact_name: str = Field(min_length=1)
    email: str = Field(min_length=3)
    phone: str = Field(min_length=1)


class LineItem(Frozen):
    sku: str = Field(min_length=1)
    description: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)
    unit: str
    unit_net_price: Decimal = Field(ge=0)
    discount_percent: Decimal = Field(ge=0, le=100)
    vat_percent: Decimal = Field(ge=0, le=100)
    line_net_total: Decimal = Field(ge=0)


class Payment(Frozen):
    method: PaymentMethod
    status: PaidStatus
    payment_date: date | None = None


class Totals(Frozen):
    net: Decimal
    vat: Decimal
    gross: Decimal


class Order(Frozen):
    external_reference: str = Field(min_length=1)
    order_date: date
    currency: str = Field(min_length=3, max_length=3)
    customer: Customer
    billing_address: Address
    delivery_address: Address
    payment: Payment
    items: tuple[LineItem, ...] = Field(min_length=1)
    totals: Totals
