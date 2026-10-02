"""The zoomed second look at one unconfirmed field (design §4), on the real sample image."""

import json
from pathlib import Path

import pytest

from image_to_cash.field_retry import locate, retry_single_field, with_value
from image_to_cash.imaging import load_image, upscale
from image_to_cash.ocr import Box, TextBox
from image_to_cash.readers.base import ReaderError

HERE = Path(__file__).parent
PAGE = tuple(
    TextBox(b["text"], Box(*b["box"]))
    for b in json.loads((HERE / "fixtures/ocr/sales-order-input-clean.ocr.json").read_text(encoding="utf-8"))
)


@pytest.fixture(scope="module")
def image():
    return upscale(load_image(HERE.parent / "samples/sales-order-input-clean.png"))


class Reader:
    def __init__(self, answer: str | Exception) -> None:
        self.answer, self.asked = answer, []

    def read_field(self, crop, field):
        self.asked.append((crop.size, field))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class ZoomedOcr:
    def __init__(self, *texts: str) -> None:
        self.texts = texts

    def recognize(self, image):
        return tuple(TextBox(text, Box(0, 0, image.width, image.height)) for text in self.texts)


def misread_sku(order):
    return with_value(order, "items[0].sku", "CHR-ERG-07")


def test_the_box_most_like_a_misread_value_is_where_it_is_printed():
    assert locate("CHR-ERG-07", PAGE).text == "CHR-ERG-01"
    assert locate("completely different", PAGE) is None


def test_a_second_reading_found_by_zoomed_ocr_corrects_the_field(image, sample_order):
    reader = Reader("CHR-ERG-01")
    retried = retry_single_field(image, misread_sku(sample_order), PAGE, reader, ZoomedOcr("CHR-ERG-01"))
    assert retried.retry.confirmed and retried.mismatches == ()
    assert retried.order.items[0].sku == "CHR-ERG-01"
    assert reader.asked[0][1] == "items[0].sku"


def test_a_second_reading_zoomed_ocr_does_not_see_stays_a_mismatch(image, sample_order):
    first = misread_sku(sample_order)
    retried = retry_single_field(image, first, PAGE, Reader("CHR-ERG-07"), ZoomedOcr("CHR-ERG-01"))
    assert not retried.retry.confirmed and retried.order == first
    assert [m.field for m in retried.mismatches] == ["items[0].sku"]


def test_a_failed_second_reading_stays_a_mismatch(image, sample_order):
    retried = retry_single_field(image, misread_sku(sample_order), PAGE, Reader(ReaderError("offline")), ZoomedOcr())
    assert not retried.retry.confirmed and retried.mismatches


def test_two_mismatches_are_not_retried(image, sample_order):
    order = with_value(misread_sku(sample_order), "items[1].sku", "MAT-DESK-07")
    assert retry_single_field(image, order, PAGE, Reader("x"), ZoomedOcr()) is None


def test_a_value_printed_fewer_times_than_claimed_is_left_to_a_person(image, sample_order):
    order = with_value(sample_order, "delivery_address.zip", "10117")  # printed once, claimed twice
    assert retry_single_field(image, order, PAGE, Reader("10117"), ZoomedOcr("10117")) is None


def test_a_value_the_schema_rejects_is_not_set(sample_order):
    assert with_value(sample_order, "items[0].quantity", "two") is None


def test_a_second_reading_that_takes_another_fields_print_is_rejected(image, sample_order):
    order = with_value(sample_order, "delivery_address.street", "Friedrichstrasse 86")  # misread
    retried = retry_single_field(image, order, PAGE, Reader("Friedrichstrasse 88"), ZoomedOcr("Friedrichstrasse 88"))
    assert not retried.retry.confirmed and retried.order == order


def test_extraction_writes_the_corrected_order_and_keeps_the_retry_on_record(sample_order):
    from image_to_cash.extract import extract

    class MisreadingReader(Reader):
        def read(self, image):
            return misread_sku(sample_order)

    class PageThenZoomedOcr:
        def recognize(self, image):
            return PAGE if image.width > 1500 else (TextBox("CHR-ERG-01", Box(0, 0, 1, 1)),)

    result = extract(HERE.parent / "samples/sales-order-input-clean.png", MisreadingReader("CHR-ERG-01"), PageThenZoomedOcr())
    assert not result.needs_review and result.retry.confirmed
    assert result.order.items[0].sku == result.normalized.products[0].sku == "CHR-ERG-01"
