from image_to_cash.ocr import Box, TextBox
from image_to_cash.reconcile import Mismatch, critical_fields, reconcile


def text_boxes(texts):
    return tuple(TextBox(text=text, box=Box(0, 0, 1, 1)) for text in texts)


def expected_texts(order):
    return tuple(expected for _, expected in critical_fields(order))


def test_critical_fields_use_printed_formats(sample_order):
    fields = dict(critical_fields(sample_order))
    assert fields["items[0].discount_percent"] == "10%"
    assert fields["items[1].discount_percent"] == "0%"
    assert fields["items[0].unit_net_price"] == "250.00"
    assert fields["totals.gross"] == "678.30"
    assert fields["payment.payment_date"] == "2026-07-18"
    assert fields["delivery_address.street"] == "Huttenstrasse 41"
    assert fields["customer.phone"] == "+49 30 3550 1420"


def test_no_mismatch_when_ocr_sees_everything(sample_order):
    assert reconcile(sample_order, text_boxes(expected_texts(sample_order))) == ()


def test_missing_sku_is_reported(sample_order):
    texts = tuple(t for t in expected_texts(sample_order) if t != "MAT-DESK-02")
    assert reconcile(sample_order, text_boxes(texts)) == (Mismatch("items[1].sku", "MAT-DESK-02"),)


def test_lookalike_characters_are_tolerated(sample_order):
    texts = tuple(t.replace("0", "O") for t in expected_texts(sample_order))
    assert reconcile(sample_order, text_boxes(texts)) == ()


def test_spacing_and_decimal_commas_are_tolerated(sample_order):
    texts = tuple(t.replace(".", ",").replace("-", " - ") for t in expected_texts(sample_order))
    assert reconcile(sample_order, text_boxes(texts)) == ()
