from decimal import Decimal

import pytest

from image_to_cash.model import PaidStatus
from image_to_cash.ocr import Box, TextBox
from image_to_cash.reconcile import Mismatch, critical_fields, reconcile


def text_boxes(texts):
    return tuple(TextBox(text=text, box=Box(0, 0, 1, 1)) for text in texts)


def expected_texts(order):
    return tuple(expected for _, expected in critical_fields(order))


def flagged(order, texts):
    return tuple(mismatch.field for mismatch in reconcile(order, text_boxes(texts)))


def without_one(texts, value):
    index = texts.index(value)
    return texts[:index] + texts[index + 1 :]


def replaced(texts, old, new):
    return tuple(new if text == old else text for text in texts)


def with_item(order, index, **changes):
    items = tuple(
        item.model_copy(update=changes) if position == index else item
        for position, item in enumerate(order.items)
    )
    return order.model_copy(update={"items": items})


def with_billing(order, **changes):
    return order.model_copy(update={"billing_address": order.billing_address.model_copy(update=changes)})


def test_critical_fields_use_printed_formats(sample_order):
    fields = dict(critical_fields(sample_order))
    assert fields["items[0].discount_percent"] == "10%"
    assert fields["items[1].discount_percent"] == "0%"
    assert fields["items[0].unit_net_price"] == "250.00"
    assert fields["totals.gross"] == "678.30"
    assert fields["payment.payment_date"] == "2026-07-18"
    assert fields["delivery_address.street"] == "Huttenstrasse 41"
    assert fields["customer.phone"] == "+49 30 3550 1420"


def test_unpaid_order_has_no_payment_date_field(sample_order):
    payment = sample_order.payment.model_copy(update={"status": PaidStatus.UNPAID, "payment_date": None})
    fields = dict(critical_fields(sample_order.model_copy(update={"payment": payment})))
    assert fields["payment.status"] == "UNPAID"
    assert "payment.payment_date" not in fields


def test_no_mismatch_when_ocr_sees_everything(sample_order):
    assert reconcile(sample_order, text_boxes(expected_texts(sample_order))) == ()


def test_empty_ocr_flags_every_field(sample_order):
    assert len(reconcile(sample_order, ())) == len(critical_fields(sample_order))


def test_missing_sku_is_reported(sample_order):
    texts = tuple(t for t in expected_texts(sample_order) if t != "MAT-DESK-02")
    assert reconcile(sample_order, text_boxes(texts)) == (Mismatch("items[1].sku", "MAT-DESK-02"),)


def test_wrong_digit_is_reported(sample_order):
    texts = replaced(expected_texts(sample_order), "450.00", "460.00")
    assert flagged(sample_order, texts) == ("items[0].line_net_total",)


def test_lookalike_characters_are_tolerated(sample_order):
    texts = tuple(t.replace("0", "O").replace("1", "l") for t in expected_texts(sample_order))
    assert reconcile(sample_order, text_boxes(texts)) == ()


def test_spacing_and_decimal_commas_are_tolerated(sample_order):
    texts = tuple(t.replace(".", ",").replace("-", " - ") for t in expected_texts(sample_order))
    assert reconcile(sample_order, text_boxes(texts)) == ()


def test_accents_and_dashes_are_tolerated(sample_order):
    texts = replaced(expected_texts(sample_order), "Huttenstrasse 41", "Hüttenstraße 41")
    texts = replaced(texts, "WEB-2026-0714-A17", "WEB–2026–0714–A17")
    assert flagged(sample_order, texts) == ()


def test_values_inside_a_merged_table_row_are_found(sample_order):
    row = "1 CHR-ERGO-01 Ergonomic Desk Chair 2 PCS 250.00 10% 19% 450.00"
    merged = {"CHR-ERGO-01", "250.00", "10%", "450.00"}
    rest = tuple(t for t in expected_texts(sample_order) if t not in merged)
    assert flagged(sample_order, (*rest, row)) == ()


@pytest.mark.parametrize(
    "printed", ["1.250,00", "1,250.00", "1 250,00", "1250.00", "EUR 1.250,00", "1.250,00 €"]
)
def test_thousands_separators_are_tolerated(sample_order, printed):
    totals = sample_order.totals.model_copy(update={"gross": Decimal("1250.00")})
    order = sample_order.model_copy(update={"totals": totals})
    assert "totals.gross" not in flagged(order, (printed,))


@pytest.mark.parametrize("printed", ["10%", "1.0%", "100%"])
def test_zero_discount_is_not_vouched_for_by_a_longer_percent(sample_order, printed):
    texts = replaced(expected_texts(sample_order), "0%", printed)
    assert flagged(sample_order, texts) == ("items[1].discount_percent",)


def test_each_field_needs_its_own_occurrence(sample_order):
    texts = without_one(expected_texts(sample_order), "19%")
    assert flagged(sample_order, texts) == ("items[1].vat_percent",)


def test_paid_is_not_vouched_for_by_unpaid(sample_order):
    texts = replaced(expected_texts(sample_order), "PAID", "UNPAID")
    assert flagged(sample_order, texts) == ("payment.status",)


def test_amount_is_not_the_tail_of_a_longer_number(sample_order):
    texts = replaced(expected_texts(sample_order), "120.00", "1120.00")
    assert flagged(sample_order, texts) == ("items[1].line_net_total",)


def test_truncated_values_are_reported(sample_order):
    order = with_item(sample_order, 0, sku="CHR-ERGO-0", unit_net_price=Decimal("50.00"))
    assert flagged(order, expected_texts(sample_order)) == ("items[0].sku", "items[0].unit_net_price")


def test_house_number_must_match_in_full(sample_order):
    order = with_billing(sample_order, street="Friedrichstrasse 8")
    assert flagged(order, expected_texts(sample_order)) == ("billing_address.street",)


def test_zip_is_not_found_inside_the_phone_number(sample_order):
    order = with_billing(sample_order, zip="30355")
    assert flagged(order, expected_texts(sample_order)) == ("billing_address.zip",)


def test_values_are_not_glued_across_boxes(sample_order):
    order = with_item(sample_order, 0, sku="CHR-ERGO-012")
    texts = (*without_one(expected_texts(sample_order), "250.00"), "Qty 2", "50.00 EUR", "2")
    assert flagged(order, texts) == ("items[0].sku", "items[0].unit_net_price")
