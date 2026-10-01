from decimal import Decimal

import pytest
from pydantic import ValidationError

from image_to_cash.model import Order, PaidStatus, PaymentMethod


def test_sample_fixture_parses(sample_order):
    assert sample_order.external_reference == "WEB-2026-0714-A17"
    assert sample_order.payment.method is PaymentMethod.BANK_TRANSFER
    assert sample_order.payment.status is PaidStatus.PAID
    assert sample_order.items[0].unit_net_price == Decimal("250.00")
    assert sample_order.totals.gross == Decimal("678.30")


def test_order_is_immutable(sample_order):
    with pytest.raises(ValidationError):
        sample_order.external_reference = "CHANGED"


def test_unknown_fields_are_rejected(sample_order):
    data = sample_order.model_dump(mode="json") | {"surprise": 1}
    with pytest.raises(ValidationError):
        Order.model_validate(data)


def test_order_needs_at_least_one_item(sample_order):
    data = sample_order.model_dump(mode="json") | {"items": []}
    with pytest.raises(ValidationError):
        Order.model_validate(data)


def test_unknown_payment_method_is_rejected(sample_order):
    data = sample_order.model_dump(mode="json")
    data = data | {"payment": data["payment"] | {"method": "Cash"}}
    with pytest.raises(ValidationError):
        Order.model_validate(data)
