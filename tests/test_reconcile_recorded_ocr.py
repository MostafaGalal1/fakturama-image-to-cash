"""The cross-check against OCR recorded from the two sample images (macOS Vision)."""

import json
from pathlib import Path

import pytest

from image_to_cash.model import Order
from image_to_cash.ocr import Box, TextBox
from image_to_cash.reconcile import critical_fields, reconcile

OCR = Path(__file__).parent / "fixtures" / "ocr"


def recorded(name: str) -> tuple[TextBox, ...]:
    return tuple(TextBox(b["text"], Box(*b["box"])) for b in json.loads((OCR / f"{name}.ocr.json").read_text(encoding="utf-8")))


def test_every_field_of_the_sample_is_confirmed_on_the_clean_image(sample_order):
    assert reconcile(sample_order, recorded("sales-order-input-clean")) == ()


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("customer.company", "Northstar Office AG"),
        ("customer.email", "marta.klein@example.com"),
        ("billing_address.city", "Hamburg"),
        ("payment.method", "Credit Card"),
    ],
)
def test_a_misread_name_city_email_or_method_is_caught(sample_order, field, wrong):
    head, _, tail = field.partition(".")
    data = sample_order.model_dump(mode="json")
    data[head][tail] = wrong
    changed = Order.model_validate(data)
    assert field in {m.field for m in reconcile(changed, recorded("sales-order-input-clean"))}


def test_a_misread_description_or_quantity_is_caught(sample_order):
    data = sample_order.model_dump(mode="json")
    data["items"][1].update(description="Anti-Fatigue Floor Mat", quantity="4")
    changed = Order.model_validate(data)
    mismatched = {m.field for m in reconcile(changed, recorded("sales-order-input-clean"))}
    assert {"items[1].description", "items[1].quantity"} <= mismatched


def test_the_pixelated_copy_confirms_almost_nothing(sample_order):
    assert len(reconcile(sample_order, recorded("sales-order-input"))) > len(critical_fields(sample_order)) // 2
