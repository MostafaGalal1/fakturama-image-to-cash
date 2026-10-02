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


def test_json_round_trip_is_lossless(sample_order):
    assert Order.model_validate_json(sample_order.model_dump_json()) == sample_order


def test_padded_text_is_stripped(sample_order):
    data = with_value(sample_order.model_dump(mode="json"), ("items", 0, "sku"), "  CHR-ERG-01 ")
    assert Order.model_validate(data).items[0].sku == "CHR-ERG-01"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("items", 0, "quantity"), "0"),
        (("items", 0, "unit_net_price"), "-1.00"),
        (("items", 0, "discount_percent"), "101"),
        (("items", 0, "vat_percent"), "19.555"),
        (("items", 0, "line_net_total"), "1E+30"),
        (("items", 0, "sku"), "   "),
        (("items", 0, "unit"), ""),
        (("totals", "net"), "-570.00"),
        (("totals", "gross"), "NaN"),
        (("currency",), "eur"),
        (("billing_address", "zip"), " "),
        (("customer", "surprise"), "x"),
    ],
)
def test_invalid_values_are_rejected_at_their_field(sample_order, path, value):
    data = with_value(sample_order.model_dump(mode="json"), path, value)
    with pytest.raises(ValidationError) as excinfo:
        Order.model_validate(data)
    assert excinfo.value.errors()[0]["loc"] == path


def with_value(data, path, value):
    """Return a copy of nested JSON-like `data` with `value` placed at `path`."""
    head, *rest = path
    new_child = value if not rest else with_value(data[head], rest, value)
    if isinstance(data, list):
        return [new_child if index == head else item for index, item in enumerate(data)]
    return data | {head: new_child}
